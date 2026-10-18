"""Layer 7: the HTTP API, behaving as it is documented. Every endpoint, the Responses wire format
and its streaming, the errors, the OpenAI SDK as a client, and what is never served."""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from harness_interface.api.app import create_app
from harness_interface.platform import Record

SLOW = 'echo start; sleep {s}; echo end; printf \'{{"status":"ok","answer":"done"}}\' > "$HI_OUTPUT"\n'


def events(text: str):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def harness(client, echo, name, script):
    spec = {**echo.to_dict(), "name": name, "scripts": {"run.sh": script}}
    assert client.put(f"/harnesses/{name}", json=spec).status_code == 200
    return name


def settled(client, rid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        d = client.get(f"/responses/{rid}").json()
        if d["status"] != "in_progress":
            return d
        time.sleep(0.05)
    raise AssertionError(f"{rid} still in progress")


# ── resources ──────────────────────────────────────────────────────────────────────────────────
def test_a_providers_key_is_never_returned(client):
    r = client.put("/providers/deepseek", json={"name": "deepseek", "url": "https://api.deepseek.com/anthropic", "key": "sk-secret"})
    assert r.status_code == 200 and r.json() == {"name": "deepseek", "url": "https://api.deepseek.com/anthropic"}
    assert "sk-secret" not in client.get("/providers").text and "sk-secret" not in client.get("/providers/deepseek").text
    assert client.delete("/providers/deepseek").json() == {"deleted": True}
    assert client.get("/providers/deepseek").status_code == 404


def test_resource_refusals(client, echo):
    assert client.put("/providers/other", json={"name": "deepseek", "url": "u", "key": "k"}).status_code == 400
    assert client.put("/providers/Bad_Name", json={"name": "Bad_Name", "url": "u", "key": "k"}).status_code == 400
    assert client.put("/harnesses/echo", json={**echo.to_dict(), "scripts": {"../x": "y"}}).status_code == 422
    assert client.put("/providers/x", json={"name": "x"}).status_code == 422


def test_default_is_built_in_and_reserved(client):
    assert [s["name"] for s in client.get("/sandboxes").json()] == ["default"]
    assert client.get("/sandboxes/default").json()["dockerfile"].startswith("#")
    assert client.put("/sandboxes/default", json={"name": "default", "dockerfile": "FROM x"}).status_code == 400
    assert client.delete("/sandboxes/default").status_code == 400
    r = client.put("/sandboxes/py", json={"name": "py", "dockerfile": "FROM python:3.12", "egress": ["pypi.org"]})
    assert r.status_code == 200 and r.json()["egress"] == ["pypi.org"]


def test_harness_scripts_land_on_disk(client, service, echo):
    d = service.registry.scripts_of("echo")
    assert (d / "run.sh").read_text() == echo.scripts["run.sh"]
    got = client.get("/harnesses/echo").json()
    assert got["provider"] == "none" and got["sandbox"] == "default" and set(got["scripts"]) == {"run.sh"}
    assert client.delete("/harnesses/echo").json() == {"deleted": True} and not d.exists()


# ── responses ──────────────────────────────────────────────────────────────────────────────────
def test_a_response_in_the_responses_shape(client, echo):
    spec = {**echo.to_dict(), "run": {**echo.to_dict()["run"], "env": {"WHERE": "{provider_url} as {model}"}}}
    client.put("/harnesses/echo", json=spec)
    body = {"model": "echo/m1", "instructions": "be brief", "metadata": {"who": "test"},
            "input": [{"type": "input_text", "text": "say hi"}, {"type": "input_file", "filename": "a.txt", "file_data": "A"}]}
    r = client.post("/responses", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert r.headers["x-response-id"] == d["id"] and d["object"] == "response" and d["status"] == "completed"
    assert d["model"] == "echo/m1" and d["instructions"] == "be brief" and d["metadata"] == {"who": "test"}
    assert d["input"] == body["input"] and d["previous_response_id"] is None
    assert d["output"] == [{"type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "echo: say hi", "annotations": []}]}]
    assert d["usage"] == {"input_tokens": 1, "output_tokens": 1} and d["error"] is None and d["incomplete_details"] is None
    h = d["harness"]
    assert (h["name"], h["provider"], h["sandbox"], h["runtime"], h["image"]) == ("echo", "none", "default", "local", None)
    assert h["exit_code"] == 0 and h["session_id"] == "echo-1" and h["files"] == ["hello.txt"] and h["latency_s"] > 0
    out = client.get(f"/responses/{d['id']}/output")
    assert out.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(line) for line in out.text.splitlines()]
    assert lines[0] == {"type": "text", "text": "echo: say hi"}
    assert lines[1]["where"] == "https://example.invalid/v1 as m1" and lines[1]["model"] == "m1"
    assert client.get(f"/responses/{d['id']}/files/AGENTS.md").text == "be brief"
    assert client.get(f"/responses/{d['id']}/files/a.txt").text == "A"
    assert client.get(f"/responses/{d['id']}").json() == d and [x["id"] for x in client.get("/responses").json()] == [d["id"]]


def test_the_stream_is_sse_in_the_responses_framing(client, echo):
    with client.stream("POST", "/responses", json={"model": "echo", "input": "go", "stream": True}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        rid = r.headers["x-response-id"]
        evs = events(b"".join(r.iter_bytes()).decode())
    assert evs[0][0] == "response.created" and evs[0][1]["response"]["id"] == rid
    assert evs[0][1]["response"]["status"] == "in_progress"
    assert [e for e, _ in evs[1:-1]] == ["harness.output"] * 2
    assert json.loads(evs[1][1]["line"]) == {"type": "text", "text": "echo: go"}
    assert evs[-1][0] == "response.completed" and evs[-1][1]["response"]["output"][0]["content"][0]["text"] == "echo: go"


def test_continuing_a_conversation(client, echo):
    first = client.post("/responses", json={"model": "echo", "input": "one"}).json()
    second = client.post("/responses", json={"model": "echo", "input": "two", "previous_response_id": first["id"]}).json()
    assert second["previous_response_id"] == first["id"] and second["harness"]["workspace"] == first["harness"]["workspace"]
    out = [json.loads(line) for line in client.get(f"/responses/{second['id']}/output").text.splitlines()]
    assert out[1]["session_id_in"] == "echo-1" and second["harness"]["files"] == []
    assert client.post("/responses", json={"model": "echo", "input": "x", "previous_response_id": "resp_nope"}).status_code == 400
    client.put("/harnesses/echo2", json={**echo.to_dict(), "name": "echo2"})
    r = client.post("/responses", json={"model": "echo2", "input": "x", "previous_response_id": first["id"]})
    assert r.status_code == 400 and "stays on its harness" in r.text


def test_errors_before_anything_runs(client, echo):
    assert client.post("/responses", json={"model": "nope", "input": "x"}).status_code == 400
    assert client.post("/responses", json={"model": "echo", "input": ""}).status_code == 422
    assert client.post("/responses", json={"model": "echo", "input": [{"type": "input_file", "filename": "a", "file_data": "b"}]}).status_code == 422
    assert client.post("/responses", json={"model": "echo", "input": [{"type": "input_text", "text": "x"},
                                           {"type": "input_file", "filename": "../a", "file_data": "b"}]}).status_code == 400
    client.delete("/providers/none")
    r = client.post("/responses", json={"model": "echo", "input": "x"})
    assert r.status_code == 400 and "provider 'none'" in r.text
    assert client.get("/responses").json() == [] and client.get("/responses/resp_nope").status_code == 404


def test_failed_timeout_and_cancelled_after(client, echo):
    harness(client, echo, "echo", "exit 3\n")
    d = client.post("/responses", json={"model": "echo", "input": "x"}).json()
    assert d["status"] == "failed" and d["error"]["code"] == "harness_failed" and d["harness"]["exit_code"] == 3 and d["output"] == []
    spec = {**echo.to_dict(), "scripts": {"run.sh": "echo start; sleep 5\n"}, "run": {**echo.to_dict()["run"], "timeout_s": 1}}
    client.put("/harnesses/echo", json=spec)
    d = client.post("/responses", json={"model": "echo", "input": "x"}).json()
    assert d["status"] == "incomplete" and d["incomplete_details"] == {"reason": "timeout"}
    assert client.post(f"/responses/{d['id']}/cancel").json() == {"cancelled": False}   # already over


# ── runs belong to the server ──────────────────────────────────────────────────────────────────
def test_a_run_outlives_its_client(live, echo, service):
    name = harness(live, echo, "slow", SLOW.format(s=1))
    with live.stream("POST", "/responses", json={"model": name, "input": "x", "stream": True}) as r:
        rid = r.headers["x-response-id"]
        assert next(r.iter_lines()) == "event: response.created"   # sent before the harness printed anything
    d = settled(live, rid)                                          # the client left; the run did not
    assert d["status"] == "completed" and service.output_path(rid).read_text() == "start\nend\n"


def test_cancel_a_running_harness(live, echo):
    name = harness(live, echo, "slow", SLOW.format(s=30))
    with live.stream("POST", "/responses", json={"model": name, "input": "x", "stream": True}) as r:
        rid = r.headers["x-response-id"]
        lines = r.iter_lines()
        while next(lines) != 'data: {"type": "harness.output", "line": "start"}':
            pass
        assert live.post(f"/responses/{rid}/cancel").json() == {"cancelled": True}
        assert "event: response.completed" in list(lines)
    d = settled(live, rid)
    assert d["status"] == "cancelled" and d["output"] == []


def test_cancel_while_the_sandbox_is_being_set_up(live, echo, service, monkeypatch):
    class Waits:
        async def start(self, spec):
            import asyncio
            await asyncio.sleep(30)
    monkeypatch.setattr(service.placement, "runtime", lambda resolved: Waits())
    with live.stream("POST", "/responses", json={"model": "echo", "input": "x", "stream": True}) as r:
        rid = r.headers["x-response-id"]
        assert live.get(f"/responses/{rid}").json()["status"] == "in_progress"
        assert live.post(f"/responses/{rid}/cancel").json() == {"cancelled": True}
    d = settled(live, rid)
    assert d["status"] == "cancelled" and d["harness"]["exit_code"] is None and not service.output_path(rid).exists()


def test_one_run_at_a_time_per_conversation(live, echo):
    name = harness(live, echo, "slow", SLOW.format(s=1))
    first = live.post("/responses", json={"model": name, "input": "one"}).json()
    with live.stream("POST", "/responses", json={"model": name, "input": "two", "stream": True,
                                                 "previous_response_id": first["id"]}) as r:
        busy = live.post("/responses", json={"model": name, "input": "three", "previous_response_id": first["id"]})
        assert busy.status_code == 409 and "in progress" in busy.json()["detail"]
        list(r.iter_lines())
    again = live.post("/responses", json={"model": name, "input": "three", "previous_response_id": first["id"]})
    assert again.status_code == 200 and again.json()["status"] == "completed"


def test_runs_go_side_by_side(live, echo):
    name = harness(live, echo, "slow", SLOW.format(s=1))
    began = time.time()
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda i: live.post("/responses", json={"model": name, "input": str(i)}).json(), range(4)))
    assert all(d["status"] == "completed" for d in results) and len({d["harness"]["workspace"] for d in results}) == 4
    assert time.time() - began < 3


def test_a_restart_closes_what_was_in_flight(service):
    lost = Record(id="resp_lost0000000000", model="echo", harness="echo", provider="none", sandbox="default",
                  runtime="local", workspace="/nowhere")
    service.records.put(lost.id, lost)
    with TestClient(create_app(service)) as c:
        d = c.get(f"/responses/{lost.id}").json()
    assert d["status"] == "failed" and d["error"]["code"] == "server_restarted"


def test_the_server_will_not_start_without_git(service, monkeypatch):
    from harness_interface import workspace
    monkeypatch.setattr(workspace.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="git is required"):
        with TestClient(create_app(service)):
            pass


# ── everything a harness did ───────────────────────────────────────────────────────────────────
SCRIPT = {
    1: 'echo "to stdout"; echo "to stderr" >&2; printf "one\\n" > a.txt; printf "x\\n" > gone.txt\n',
    2: 'echo "turn two"; printf "two\\n" > a.txt; rm gone.txt; printf \'{"status":"ok","session_id":"s"}\' > "$HI_OUTPUT"\n',
}


def test_stdout_and_stderr_stream_and_are_kept(client, echo):
    name = harness(client, echo, "seen", SCRIPT[1])
    with client.stream("POST", "/responses", json={"model": name, "input": "x", "stream": True}) as r:
        evs = events(b"".join(r.iter_bytes()).decode())
    middle = [(e, d["line"]) for e, d in evs[1:-1]]
    assert ("harness.output", "to stdout") in middle and ("harness.log", "to stderr") in middle
    assert client.get(f"/responses/{evs[0][1]['response']['id']}/log").text == "to stderr\n"


def test_every_change_and_each_turns_files(client, echo):
    name = harness(client, echo, "seen", SCRIPT[1])
    first = client.post("/responses", json={"model": name, "input": "x"}).json()
    assert first["harness"]["files"] == ["a.txt", "gone.txt"] and first["harness"]["deleted"] == []
    harness(client, echo, "seen", SCRIPT[2])
    second = client.post("/responses", json={"model": name, "input": "y", "previous_response_id": first["id"]}).json()
    h = second["harness"]
    assert h["files"] == ["a.txt"] and h["deleted"] == ["gone.txt"] and h["base"] != h["commit"]
    diff = client.get(f"/responses/{second['id']}/diff").text
    assert "-one" in diff and "+two" in diff and "deleted file mode" in diff
    assert client.get(f"/responses/{first['id']}/files/a.txt").text == "one\n"
    assert client.get(f"/responses/{second['id']}/files/a.txt").text == "two\n"
    assert client.get(f"/responses/{second['id']}/files/gone.txt").status_code == 404
    assert "gone.txt" in client.get(f"/responses/{first['id']}/files").json()
    assert "gone.txt" not in client.get(f"/responses/{second['id']}/files").json()


def test_the_diff_is_live_while_the_harness_works(live, echo):
    name = harness(live, echo, "slowdiff", 'printf "draft\\n" > notes.md; sleep 3; printf \'{"status":"ok"}\' > "$HI_OUTPUT"\n')
    with live.stream("POST", "/responses", json={"model": name, "input": "x", "stream": True}) as r:
        rid = r.headers["x-response-id"]
        deadline, diff = time.time() + 5, ""
        while "+draft" not in diff and time.time() < deadline:
            diff = live.get(f"/responses/{rid}/diff").text
            time.sleep(0.2)
        assert "+draft" in diff and live.get(f"/responses/{rid}").json()["status"] == "in_progress"
        assert "notes.md" in live.get(f"/responses/{rid}/files").json()
        assert live.get(f"/responses/{rid}/files/.hi/request.json").status_code == 404   # internal, even mid-run
        list(r.iter_lines())


def test_a_projects_gitignore_never_exposes_the_harnesss_own_state(client, echo):
    name = harness(client, echo, "private", 'mkdir -p .home && echo secret > .home/auth.json; echo code > app.py\n')
    body = {"model": name, "input": [{"type": "input_text", "text": "x"},
                                     {"type": "input_file", "filename": ".gitignore", "file_data": "build/\n"}]}
    d = client.post("/responses", json=body).json()
    assert d["harness"]["files"] == ["app.py"]
    diff = client.get(f"/responses/{d['id']}/diff").text
    listed = client.get(f"/responses/{d['id']}/files").json()
    assert "secret" not in diff and ".home" not in diff and not any(p.startswith((".home", ".hi")) for p in listed)
    assert client.get(f"/responses/{d['id']}/files/.home/auth.json").status_code == 404


# ── the OpenAI SDK as a client ─────────────────────────────────────────────────────────────────
def test_the_openai_sdk_works_unchanged(live, echo):
    from openai import OpenAI
    sdk = OpenAI(base_url=str(live.base_url), api_key="unused")
    first = sdk.responses.create(model="echo", input="one")
    assert first.status == "completed" and first.output_text == "echo: one"
    second = sdk.responses.create(model="echo", input="two", previous_response_id=first.id)
    assert second.previous_response_id == first.id and second.output_text == "echo: two"
    assert sdk.responses.retrieve(first.id).output_text == "echo: one"
    kinds = [e.type for e in sdk.responses.create(model="echo", input="three", stream=True)]
    assert kinds[0] == "response.created" and kinds[-1] == "response.completed" and "harness.output" in kinds
