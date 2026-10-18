"""A run belongs to the server: it outlives its client, can be cancelled at any point, holds its
conversation while it runs, runs beside others, and is closed out by a restart."""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from harness_interface.models import HarnessInfo, Response

SLOW = 'echo start; sleep {s}; echo end; printf \'{{"status":"ok","answer":"done"}}\' > "$HI_OUTPUT"\n'


def slow(client, echo, seconds=1, name="slow"):
    spec = {**echo.model_dump(mode="json"), "name": name}
    spec["scripts"] = {"run.sh": SLOW.format(s=seconds)}
    assert client.put(f"/harnesses/{name}", json=spec).status_code == 200
    return name


def settled(client, rid, timeout=10):
    """The record once its run is over."""
    end = time.time() + timeout
    while time.time() < end:
        d = client.get(f"/responses/{rid}").json()
        if d["status"] != "in_progress":
            return d
        time.sleep(0.05)
    raise AssertionError(f"{rid} still in progress")


def test_a_run_outlives_its_client(live, echo, container):
    client = live
    name = slow(client, echo)
    with client.stream("POST", "/responses", json={"model": name, "input": "x", "stream": True}) as r:
        rid = r.headers["x-response-id"]
        first = next(r.iter_lines())
        assert first == "event: response.created"            # sent before the harness has printed anything
    d = settled(client, rid)                                  # the client left; the run did not
    assert d["status"] == "completed" and d["harness"]["exit_code"] == 0
    assert container.settings.out_path(rid).read_text() == "start\nend\n"
    assert client.post(f"/responses/{rid}/cancel").json() == {"cancelled": False}


def test_cancel_a_running_harness(live, echo):
    client = live
    name = slow(client, echo, seconds=30)
    with client.stream("POST", "/responses", json={"model": name, "input": "x", "stream": True}) as r:
        rid = r.headers["x-response-id"]
        lines = r.iter_lines()
        while next(lines) != 'data: {"type": "harness.output", "line": "start"}':
            pass
        assert client.post(f"/responses/{rid}/cancel").json() == {"cancelled": True}
        assert "event: response.completed" in list(lines)       # the stream ends with the record
    d = settled(client, rid)
    assert d["status"] == "cancelled" and d["output"] == []


def test_cancel_while_the_sandbox_is_being_set_up(live, echo, container, monkeypatch):
    client = live
    runtime = container.service.runtime
    async def slow_image(sandbox):
        import asyncio
        await asyncio.sleep(1)
    monkeypatch.setattr(runtime, "image", slow_image)
    with client.stream("POST", "/responses", json={"model": "echo", "input": "x", "stream": True}) as r:
        rid = r.headers["x-response-id"]
        assert client.get(f"/responses/{rid}").json()["status"] == "in_progress"   # visible before setup ends
        assert client.post(f"/responses/{rid}/cancel").json() == {"cancelled": True}
    d = settled(client, rid)
    assert d["status"] == "cancelled" and d["harness"]["exit_code"] is None    # the harness never started
    assert not container.settings.out_path(rid).exists()


def test_a_failed_setup_is_recorded(client, echo, container, monkeypatch):
    async def broken(sandbox):
        raise RuntimeError("sandbox 'default' failed to build")
    monkeypatch.setattr(container.service.runtime, "image", broken)
    d = client.post("/responses", json={"model": "echo", "input": "x"}).json()
    assert d["status"] == "failed" and d["error"] == {"code": "setup_failed", "message": "sandbox 'default' failed to build"}


def test_one_run_at_a_time_per_conversation(live, echo):
    client = live
    name = slow(client, echo)
    first = client.post("/responses", json={"model": name, "input": "one"}).json()
    with client.stream("POST", "/responses", json={"model": name, "input": "two", "stream": True,
                                                   "previous_response_id": first["id"]}) as r:
        busy = client.post("/responses", json={"model": name, "input": "three", "previous_response_id": first["id"]})
        assert busy.status_code == 409 and "already has a run in progress" in busy.json()["detail"]
        list(r.iter_lines())
    again = client.post("/responses", json={"model": name, "input": "three", "previous_response_id": first["id"]})
    assert again.status_code == 200 and again.json()["status"] == "completed"   # free once the run is over


def test_runs_go_side_by_side(live, echo):
    client = live
    name = slow(client, echo, seconds=1)
    began = time.time()
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda i: client.post("/responses", json={"model": name, "input": str(i)}).json(), range(4)))
    assert all(d["status"] == "completed" for d in results)
    assert len({d["harness"]["workspace"] for d in results}) == 4
    assert time.time() - began < 3                            # four one-second runs, together, not one after another


@pytest.mark.anyio
async def test_a_restart_closes_what_was_in_flight(container):
    lost = Response(model="echo", input="x", harness=HarnessInfo(name="echo", provider="none", sandbox="default",
                                                                 runtime="local", workspace="/nowhere"))
    container.responses.put(lost.id, lost)
    await container.service.recover()
    d = container.responses.get(lost.id)
    assert d.status == "failed" and d.error["code"] == "server_restarted"
    assert not list(container.settings.responses.glob(".*.tmp"))   # records are written whole


@pytest.mark.anyio
async def test_cancel_reaches_the_loop_from_any_thread():
    """The cancel endpoint runs on a worker thread; Docker's kill needs the event loop."""
    import asyncio
    from harness_interface.runtime import Process
    proc = await asyncio.create_subprocess_exec("sleep", "30", stdout=asyncio.subprocess.PIPE)

    def kill():
        asyncio.get_running_loop()                # raises off the loop, as `docker kill` scheduling would
        proc.kill()
    p = Process(proc, 60, kill)
    await asyncio.to_thread(p.cancel)
    assert await asyncio.wait_for(p.wait(), 5) != 0 and p.cancelled


@pytest.fixture
def anyio_backend():
    return "asyncio"
