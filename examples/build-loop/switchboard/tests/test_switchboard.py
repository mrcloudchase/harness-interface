"""The acceptance suite for switchboard. The build loop owns this file: it is never changed by
the harnesses building the project."""
import pytest
from fastapi.testclient import TestClient

from switchboard.app import app


@pytest.fixture
def client():
    return TestClient(app)


def add(client, name, command, **extra):
    return client.put(f"/harnesses/{name}", json={"name": name, "command": command, **extra})


# ── harnesses ─────────────────────────────────────────────────────────────────────────────────
def test_add_and_get_a_harness(client):
    r = add(client, "echo", ["sh", "-c", "echo hi"])
    assert r.status_code == 200 and r.json()["name"] == "echo" and r.json()["command"] == ["sh", "-c", "echo hi"]
    assert client.get("/harnesses/echo").json()["command"] == ["sh", "-c", "echo hi"]


def test_timeout_defaults_to_30(client):
    assert add(client, "t30", ["true"]).json()["timeout_s"] == 30


def test_list_is_sorted(client):
    add(client, "zeta", ["true"])
    add(client, "alpha", ["true"])
    names = [h["name"] for h in client.get("/harnesses").json()]
    assert names == sorted(names) and {"zeta", "alpha"} <= set(names)


def test_name_must_match_the_path(client):
    assert client.put("/harnesses/one", json={"name": "two", "command": ["true"]}).status_code == 400


def test_invalid_harnesses_are_refused(client):
    assert add(client, "Bad_Name", ["true"]).status_code == 422
    assert add(client, "empty", []).status_code == 422


def test_missing_harness_is_404(client):
    assert client.get("/harnesses/nope").status_code == 404


def test_delete(client):
    add(client, "gone", ["true"])
    assert client.delete("/harnesses/gone").json() == {"deleted": True}
    assert client.delete("/harnesses/gone").json() == {"deleted": False}
    assert client.get("/harnesses/gone").status_code == 404


# ── runs ──────────────────────────────────────────────────────────────────────────────────────
def test_a_run_gets_the_task_three_ways(client):
    add(client, "taskecho", ["sh", "-c", 'read line; echo "stdin=$line env=$TASK sb=$SWITCHBOARD_TASK"'])
    r = client.post("/runs", json={"harness": "taskecho", "task": "hello"})
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "completed" and run["exit_code"] == 0
    assert run["output"].strip() == "stdin=hello env=hello sb=hello"
    assert run["id"].startswith("run_") and run["harness"] == "taskecho" and run["task"] == "hello"


def test_stderr_is_the_log(client):
    add(client, "noisy", ["sh", "-c", "echo out; echo err >&2"])
    run = client.post("/runs", json={"harness": "noisy", "task": "x"}).json()
    assert run["output"].strip() == "out" and run["log"].strip() == "err"


def test_a_failing_command_is_failed(client):
    add(client, "boom", ["sh", "-c", "exit 3"])
    run = client.post("/runs", json={"harness": "boom", "task": "x"}).json()
    assert run["status"] == "failed" and run["exit_code"] == 3


def test_a_slow_command_times_out(client):
    add(client, "slow", ["sh", "-c", "sleep 5"], timeout_s=0.5)
    run = client.post("/runs", json={"harness": "slow", "task": "x"}).json()
    assert run["status"] == "timeout" and run["exit_code"] is None


def test_bad_runs_are_refused(client):
    assert client.post("/runs", json={"harness": "nope", "task": "x"}).status_code == 400
    add(client, "ok", ["true"])
    assert client.post("/runs", json={"harness": "ok", "task": "   "}).status_code == 400


def test_runs_are_recorded(client):
    add(client, "rec", ["sh", "-c", "echo recorded"])
    run = client.post("/runs", json={"harness": "rec", "task": "x"}).json()
    assert client.get(f"/runs/{run['id']}").json() == run
    assert run["id"] in [r["id"] for r in client.get("/runs").json()]
    assert client.get("/runs/run_missing").status_code == 404


def test_ids_are_unique(client):
    add(client, "uniq", ["true"])
    ids = {client.post("/runs", json={"harness": "uniq", "task": "x"}).json()["id"] for _ in range(5)}
    assert len(ids) == 5


def test_a_run_continues_an_earlier_one(client):
    add(client, "memory", ["sh", "-c", 'echo "before=[$PREVIOUS_OUTPUT] now=$TASK"'])
    first = client.post("/runs", json={"harness": "memory", "task": "one"}).json()
    second = client.post("/runs", json={"harness": "memory", "task": "two", "previous_run_id": first["id"]}).json()
    assert second["previous_run_id"] == first["id"]
    assert "before=[before=[] now=one" in second["output"] and "now=two" in second["output"]


def test_continuing_needs_the_same_harness(client):
    add(client, "a1", ["true"])
    add(client, "b1", ["true"])
    first = client.post("/runs", json={"harness": "a1", "task": "x"}).json()
    assert client.post("/runs", json={"harness": "b1", "task": "y", "previous_run_id": first["id"]}).status_code == 400
    assert client.post("/runs", json={"harness": "a1", "task": "y", "previous_run_id": "run_nope"}).status_code == 400
