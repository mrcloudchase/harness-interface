"""Layer 3: one response on any runtime, here this machine. It streams what the harness prints and
every steer sent; a steer lands in the running work, or is refused when it can't be delivered; a stop
is graceful, a stop that hangs is a kill, and the folder's timeout stops it too; a response cut off
while it said `running` can be resumed; the provider's key never reaches the harness under the
gateway; and a cancel at any point leaves nothing running."""
import asyncio
import json
import os
import subprocess
import time

import pytest

from harness_interface.errors import Invalid
from harness_interface.execution import Outcome
from harness_interface.harness.contract import Request, session_token
from harness_interface.harness.folder import HarnessFolder
from harness_interface.harness.install import Installed
from harness_interface.harness.placement import Placement
from harness_interface.harness.response import Response
from harness_interface.runtimes.docker import Provider
from harness_interface.workspace import Workspace
from standin import TEMPLATE, events, tools, variant
from upstream import Upstream

KEY = "sk-real-provider-key-" + os.urandom(6).hex()


@pytest.fixture
def setup(tmp_path):
    installed = Installed(tools(tmp_path / "tools"), None, True, tmp_path / "install.log")
    return {"installed": installed, "workspace": Workspace(tmp_path / "s" / "workspace"), "tmp": tmp_path}


async def start(setup, request, folder=None, n=1, **kw) -> Response:
    return await Response.start(folder or HarnessFolder.load(TEMPLATE), setup["installed"], setup["workspace"],
                                request, placement=kw.pop("placement", Placement()),
                                rundir=setup["tmp"] / f"run-{n}", **kw)


async def follow(response, on=None):
    """Every event, by stream; `on(event, so_far)` runs on each stdout event as it arrives."""
    out = {}
    async for event in response.events():
        out[event.stream] = out.get(event.stream, b"") + event.data
        if on and event.stream == "stdout":
            await on(events(out["stdout"]))
    return out


def gone(marker: str) -> bool:
    """Whether every process started under `marker` has ended (a CLI ends once its adapter is gone)."""
    deadline = time.monotonic() + 10
    while subprocess.run(["pgrep", "-f", marker], capture_output=True).stdout:
        if time.monotonic() > deadline:
            return False
        time.sleep(0.05)
    return True


def counted(seen) -> int:
    return max([e["n"] for e in seen if e.get("type") == "count"], default=0)


def test_a_response_streams_the_harness_and_reports_its_result(setup):
    async def go():
        r = await start(setup, Request("count to 3"))
        return await follow(r), await r.result()
    out, result = asyncio.run(go())
    seen = events(out["stdout"])
    assert [e["n"] for e in seen if e["type"] == "count"] == [1, 2, 3]
    assert (result.status, result.answer, result.steers_sent, result.stop) == ("ok", "Counted to 3.", 0, None)
    assert result.output["count"] == 3 and result.changes == {"count.txt": b"1\n2\n3\n"}


def test_a_steer_lands_in_the_running_work(setup):
    async def go():
        r = await start(setup, Request("count to 30"))

        async def on(seen):
            if counted(seen) == 2 and r.steers_sent == 0:
                await r.steer("now count to 4")
        return await follow(r, on), await r.result()
    out, result = asyncio.run(go())
    seen = events(out["stdout"])
    assert out["steer"] == b"now count to 4"
    assert any(e["type"] == "steer_accepted" and e["target"] == 4 for e in seen)
    assert (result.status, result.answer, result.steers, result.steers_sent, result.undelivered) == \
        ("ok", "Counted to 4.", 1, 1, 0)


def test_a_steer_that_cant_be_delivered_is_refused(setup):
    async def go():
        r = await start(setup, Request("count to 30"))

        async def on(seen):
            if counted(seen) == 1 and not r.stopping:
                r.stop()
                with pytest.raises(Invalid, match="stopping"):
                    await r.steer("too late")
        await follow(r, on)
        result = await r.result()
        with pytest.raises(Invalid):
            await r.steer("after the end")
        with pytest.raises(Invalid):
            await r.steer("   ")
        return result
    assert asyncio.run(go()).steers_sent == 0


def test_a_harness_that_isnt_steered_takes_no_steers(setup):
    folder = variant(setup["tmp"] / "continued", lambda s: s["run"].update(interrupt="continued"))

    async def go():
        r = await start(setup, Request("count to 2"), folder)
        with pytest.raises(Invalid, match="continued"):
            await r.steer("more")
        return await r.result()
    assert asyncio.run(go()).status == "ok"


def test_a_stop_is_graceful_and_the_response_can_be_continued(setup):
    async def go():
        r = await start(setup, Request("count to 100"))

        async def on(seen):
            if counted(seen) == 2:
                r.stop()
        out = await follow(r, on)
        first = await r.result()
        again = await start(setup, Request("count to 5", resume=first.resume), n=2)
        return events(out["stdout"]), first, await follow(again), await again.result()
    seen, first, out, second = asyncio.run(go())
    assert {"type": "hi.stop", "why": "SIGINT"} in seen
    assert (first.status, first.stop, first.outcome.kind) == ("stopped", "requested", "stopped") and first.resume
    resumed = next(e for e in events(out["stdout"]) if e["type"] == "session")
    assert resumed["resumed"] and resumed["count"] == first.output["count"]
    assert (second.status, second.answer) == ("ok", "Counted to 5.")


def test_a_response_cut_off_while_running_is_stopped_and_resumes(setup):
    """A stop that can't wait is a kill: HI_OUTPUT still says `running`, with the resume it wrote early."""
    async def go():
        r = await start(setup, Request("count to 100"))

        async def on(seen):
            if counted(seen) == 2:
                r.stop(timeout_s=0)
        await follow(r, on)
        first = await r.result()
        again = await start(setup, Request("count to 4", resume=first.resume), n=2)
        await follow(again)
        return first, await again.result()
    first, second = asyncio.run(go())
    assert first.outcome == Outcome.killed() and first.output["status"] == "running"
    assert first.status == "stopped" and first.resume
    assert (second.status, second.answer) == ("ok", "Counted to 4.")
    counts = (setup["workspace"].path / "count.txt").read_text().split()
    assert counts == [str(n) for n in range(1, 5)]                       # it carried on where it was cut off


def test_the_folders_timeout_stops_the_response_gracefully(setup):
    folder = variant(setup["tmp"] / "quick", lambda s: s["run"].update(timeout_s=0.8))

    async def go():
        r = await start(setup, Request("count to 100"), folder)
        await follow(r)
        return await r.result()
    result = asyncio.run(go())
    assert (result.status, result.stop, result.outcome.kind) == ("stopped", "timeout", "stopped")


def test_a_provider_the_harness_cant_speak_or_a_url_it_would_guess_at_is_refused(setup):
    one_shape = variant(setup["tmp"] / "one", lambda s: s.update(apis=["anthropic-messages"]))
    for folder, provider in ((one_shape, Provider("https://api.openai.com/v1", "openai-chat", KEY, token="t")),
                             (None, Provider("https://api.anthropic.com/v1", "anthropic-messages", KEY, token="t"))):
        with pytest.raises(Invalid):
            asyncio.run(start(setup, Request("t"), folder, provider=provider))
    assert not (setup["tmp"] / "run-1").exists()                          # refused before anything ran


def test_under_the_gateway_the_harness_reaches_its_provider_and_never_holds_the_key(setup):
    up = Upstream(setup["tmp"])
    provider = Provider(up.url + "/anthropic", "anthropic-messages", KEY, token=session_token("anthropic-messages"))

    async def go():
        r = await start(setup, Request("count to 1"), provider=provider, placement=Placement(ca_file=up.ca))
        return await follow(r), await r.result()
    try:
        out, result = asyncio.run(go())
    finally:
        up.close()
    assert {"type": "provider", "status": 200} in events(out["stdout"]) and result.status == "ok"
    assert f"x-api-key: {KEY}" in up.requests[0].decode("latin-1")
    for root in (setup["tmp"] / "s", setup["tmp"] / "run-1", setup["installed"].path):
        for p in root.rglob("*"):
            assert not p.is_file() or KEY.encode() not in p.read_bytes(), p
    assert KEY.encode() not in b"".join(out.values()) and KEY not in json.dumps(dict(result.output))


def test_a_cancel_at_any_point_of_the_start_leaves_nothing_running(setup):
    marker = str(setup["tmp"])

    async def cancel_after(steps):
        task = asyncio.ensure_future(start(setup, Request("count to 100")))
        for _ in range(steps):
            await asyncio.sleep(0)
        task.cancel()
        try:
            r = await task
        except asyncio.CancelledError:
            return False
        r.stop(0)
        await r.result()
        return True
    for steps in range(0, 40, 3):
        if asyncio.run(cancel_after(steps)):
            break
    assert gone(marker)


def test_cancelling_the_result_kills_the_response_and_waits_for_its_end(setup):
    async def go():
        r = await start(setup, Request("count to 100"))
        waiting = asyncio.ensure_future(r.result())

        async def on(seen):
            if counted(seen) == 1 and not waiting.done():
                waiting.cancel()
        await follow(r, on)
        with pytest.raises(asyncio.CancelledError):
            await waiting
        return await r.result()
    result = asyncio.run(go())
    assert result.outcome == Outcome.killed()
    assert gone(str(setup["tmp"]))
