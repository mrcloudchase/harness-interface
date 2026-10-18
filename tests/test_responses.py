"""The whole path with the echo harness: run, stream, record, continue, cancel, timeout, files."""
import json
from pathlib import Path

import pytest

from harness_interface.workspace import Workspace


def events(text):
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_run_records_the_responses_shape(client, echo):
    spec = echo.model_dump(mode="json")
    spec["run"]["env"] = {"WHERE": "{provider_url} as {model}"}          # the harness's own env is templated
    client.put("/harnesses/echo", json=spec)
    body = {"model": "echo/m1", "instructions": "be brief", "metadata": {"who": "test"},
            "input": [{"type": "input_text", "text": "say hi"}, {"type": "input_file", "filename": "a.txt", "file_data": "A"}]}
    r = client.post("/responses", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert r.headers["x-response-id"] == d["id"] and d["object"] == "response" and d["status"] == "completed"
    assert d["model"] == "echo/m1" and d["instructions"] == "be brief" and d["metadata"] == {"who": "test"}
    assert d["output"] == [{"type": "message", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": "echo: say hi", "annotations": []}]}]
    assert d["usage"] == {"input_tokens": 1, "output_tokens": 1} and d["error"] is None
    h = d["harness"]
    assert h["name"] == "echo" and h["provider"] == "none" and h["sandbox"] == "default" and h["runtime"] == "local"
    assert h["exit_code"] == 0 and h["session_id"] == "echo-1" and h["files"] == ["hello.txt"] and h["latency_s"] > 0
    # the harness saw the contract
    out = client.get(f"/responses/{d['id']}/output")
    assert out.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(l) for l in out.text.splitlines()]
    assert lines[0] == {"type": "text", "text": "echo: say hi"}
    assert lines[1] == {"type": "env", "session_id_in": "", "model": "m1", "provider_url": "https://example.invalid/v1",
                        "where": "https://example.invalid/v1 as m1"}
    assert client.get(f"/responses/{d['id']}/files/hello.txt").text.strip() == "hello from echo"
    assert client.get(f"/responses/{d['id']}/files/AGENTS.md").text == "be brief"
    assert client.get(f"/responses/{d['id']}/files/a.txt").text == "A"
    with pytest.raises(ValueError):                                # the client normalizes "..", so the guard is tested directly
        Workspace(Path(h["workspace"])).resolve("../../x")
    assert client.get(f"/responses/{d['id']}/log").status_code == 200
    assert client.get(f"/responses/{d['id']}").json() == d
    assert [x["id"] for x in client.get("/responses").json()] == [d["id"]]


def test_stream_is_sse_in_the_responses_framing(client, echo):
    with client.stream("POST", "/responses", json={"model": "echo", "input": "go", "stream": True}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        rid = r.headers["x-response-id"]
        evs = events(b"".join(r.iter_bytes()).decode())
    assert evs[0][0] == "response.created" and evs[0][1]["response"]["id"] == rid and evs[0][1]["response"]["status"] == "in_progress"
    assert [e for e, _ in evs[1:-1]] == ["harness.output"] * 2
    assert json.loads(evs[1][1]["line"]) == {"type": "text", "text": "echo: go"}
    assert evs[-1][0] == "response.completed" and evs[-1][1]["response"]["status"] == "completed"
    assert evs[-1][1]["response"]["output"][0]["content"][0]["text"] == "echo: go"


def test_previous_response_continues_in_the_same_workspace(client, echo):
    first = client.post("/responses", json={"model": "echo", "input": "one"}).json()
    second = client.post("/responses", json={"model": "echo", "input": "two", "previous_response_id": first["id"]}).json()
    assert second["previous_response_id"] == first["id"] and second["harness"]["workspace"] == first["harness"]["workspace"]
    out = [json.loads(l) for l in client.get(f"/responses/{second['id']}/output").text.splitlines()]
    assert out[1]["session_id_in"] == "echo-1"                    # the resume handle the first run reported
    assert second["harness"]["files"] == []                       # hello.txt unchanged since the first run
    assert client.post("/responses", json={"model": "echo", "input": "x", "previous_response_id": "resp_nope"}).status_code == 400
    other = {**echo.model_dump(mode="json"), "name": "echo2"}
    client.put("/harnesses/echo2", json=other)
    r = client.post("/responses", json={"model": "echo2", "input": "x", "previous_response_id": first["id"]})
    assert r.status_code == 400 and "stays on its harness" in r.text


def test_errors_before_anything_runs(client, echo):
    assert client.post("/responses", json={"model": "nope", "input": "x"}).status_code == 400
    assert client.post("/responses", json={"model": "echo", "input": ""}).status_code == 422
    assert client.post("/responses", json={"model": "echo", "input": [{"type": "input_file", "filename": "a", "file_data": "b"}]}).status_code == 422
    client.delete("/providers/none")
    r = client.post("/responses", json={"model": "echo", "input": "x"})
    assert r.status_code == 400 and "provider 'none'" in r.text
    assert client.get("/responses").json() == []


def test_failed_timeout_and_cancel(client, echo):
    spec = echo.model_dump(mode="json")
    spec["scripts"]["run.sh"] = "exit 3\n"
    client.put("/harnesses/echo", json=spec)
    d = client.post("/responses", json={"model": "echo", "input": "x"}).json()
    assert d["status"] == "failed" and d["error"]["code"] == "harness_failed" and d["harness"]["exit_code"] == 3 and d["output"] == []

    spec["scripts"]["run.sh"] = "echo start; sleep 5\n"
    spec["run"]["timeout_s"] = 1
    client.put("/harnesses/echo", json=spec)
    d = client.post("/responses", json={"model": "echo", "input": "x"}).json()
    assert d["status"] == "incomplete" and d["incomplete_details"] == {"reason": "timeout"}
    assert client.post(f"/responses/{d['id']}/cancel").json() == {"cancelled": False}   # already over
