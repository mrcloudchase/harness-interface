"""The whole path with the echo harness: apply, run, stream, record, resume, cancel."""
import json


def ndjson(text):
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def test_apply_runs_check_and_lists(client, echo):
    h = client.get("/harnesses/echo").json()
    assert h["version"] == 1 and h["check_ok"] is True
    assert [c["name"] for c in client.get("/harnesses").json()] == ["echo"]
    assert client.put(f"/harnesses/{echo.name}", json=echo.model_dump(mode="json")).json()["version"] == 2


def test_route_default_must_exist(client, echo):
    r = client.put("/route", json={"kind": "Route", "engine": "static", "default": "nope"})
    assert r.status_code == 400


def test_run_streams_records_and_resumes(client, echo):
    body = {"task": "say hi", "instructions": "be brief", "model": "m1",
            "files": [{"name": "a.txt", "content": "A"}], "check": "test -f hello.txt"}
    with client.stream("POST", "/runs", json=body) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")
        run_id, session_id = r.headers["x-run-id"], r.headers["x-session-id"]
        assert r.headers["x-harness"] == "echo"
        text = b"".join(r.iter_bytes()).decode()
    events = ndjson(text)
    assert events[0] == {"type": "text", "text": "echo: say hi"}
    assert events[1] == {"type": "env", "session_id_in": "", "model": "m1"}

    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "ok" and run["exit_code"] == 0
    assert run["files"] == ["hello.txt"]              # inputs and harness-written files are the baseline
    assert run["usage"] == {"input_tokens": 1, "output_tokens": 1}
    assert run["check"]["pass"] is True
    assert run["decision"]["reason"] == "static default"
    assert client.get(f"/runs/{run_id}/files/hello.txt").text.strip() == "hello from echo"
    assert client.get(f"/runs/{run_id}/files/AGENTS.md").text == "be brief"

    session = client.get(f"/sessions/{session_id}").json()
    assert session["harness"] == "echo" and session["session_id"] == "echo-1"

    r2 = client.post("/runs", json={"task": "again", "session": session_id, "stream": False})
    assert r2.status_code == 200
    d = r2.json()
    assert ndjson(d["body"])[1]["session_id_in"] == "echo-1"
    assert d["run"]["decision"] is None and d["run"]["harness"] == "echo"
    assert d["run"]["files"] == []                   # hello.txt unchanged since last commit


def test_pin_and_errors(client, echo):
    r = client.post("/runs", json={"task": "x", "harness": "nope", "stream": False})
    assert r.status_code == 400
    r = client.post("/runs", json={"task": "x", "session": "s_nope", "stream": False})
    assert r.status_code == 400
    r = client.post("/runs", json={"task": "x", "harness": "echo", "stream": False})
    assert r.status_code == 200 and r.json()["run"]["decision"]["reason"] == "pinned by request"


def test_secret_required(client, echo):
    spec = echo.model_dump(mode="json")
    spec["secrets"] = ["NOT_SET_ANYWHERE_XYZ"]
    client.put("/harnesses/echo", json=spec)
    r = client.post("/runs", json={"task": "x", "harness": "echo", "stream": False})
    assert r.status_code == 400 and "NOT_SET_ANYWHERE_XYZ" in r.text
    client.put("/secrets/NOT_SET_ANYWHERE_XYZ", content="v")
    assert client.get("/secrets").json() == ["NOT_SET_ANYWHERE_XYZ"]
    assert client.post("/runs", json={"task": "x", "harness": "echo", "stream": False}).status_code == 200


def test_timeout(client, echo):
    spec = echo.model_dump(mode="json")
    spec["run"]["argv"] = ["bash", "-c", "echo start; sleep 5"]
    spec["run"]["timeout_s"] = 1
    client.put("/harnesses/echo", json=spec)
    r = client.post("/runs", json={"task": "x", "harness": "echo", "stream": False})
    assert r.json()["run"]["status"] == "timeout"
