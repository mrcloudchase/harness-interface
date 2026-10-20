"""Layer 6: the HTTP API, as docs/users/api.md says, with the template's stand-in on this machine.
Every route and every error; the Responses shape with its `harness` object; the stream's events and
their order, a steer among the output and an interrupt before its continuation; interrupt's and
stop's outcomes; a response outliving its client; one response per session; the OpenAI SDK as a
client, unchanged; artifacts while it runs and after; a restart; and no key in anything served."""
import base64
import json
import os
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from harness_interface import Placement, Sessions
from harness_interface.api.app import build, create_app
from harness_interface.api.config import Settings
from harness_interface.runtimes.docker import owner_of
from harness_interface.sessions import ResponseRecord, Session
from standin import TEMPLATE
from test_sessions import DEAF
from test_store import template_map
from upstream import Upstream

KEY = "sk-api-test-key-" + os.urandom(6).hex()


@pytest.fixture
def up(tmp_path):
    u = Upstream(tmp_path)
    yield u
    u.close()


@pytest.fixture
def sessions(tmp_path, up):
    return Sessions(tmp_path / "data", Placement(ca_file=up.ca))


@pytest.fixture
def client(sessions):
    with TestClient(create_app(sessions)) as c:     # one event loop for the test, so responses run on
        yield c


def register(c, up, name="template", change=None, **files):
    """The stand-in provider and the template (as `name`, changed by `change`), ready to run."""
    url = up.url + "/anthropic"
    assert c.put("/providers/up", json={"url": url, "api": "anthropic-messages", "key": KEY}).status_code == 200

    def spec(sp):
        sp.update(name=name)
        sp["provider"]["url"] = url
        if change:
            change(sp)
    r = c.put(f"/harnesses/{name}", json=template_map(spec, **files))
    assert r.status_code == 200, r.text
    return settled_install(c, name)


def settled_install(c, name):
    deadline = time.monotonic() + 30
    while (got := c.get(f"/harnesses/{name}").json())["install"]["state"] == "installing":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    return got


@pytest.fixture
def template(client, up):
    register(client, up)
    return "template"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live(sessions, up):
    """The app on a real server, for streams still running, clients that leave, and the SDK."""
    server = uvicorn.Server(uvicorn.Config(create_app(sessions), host="127.0.0.1", port=free_port(),
                                           log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.01)
    with httpx.Client(base_url=f"http://127.0.0.1:{server.config.port}", timeout=60) as c:
        register(c, up)
        yield c
    server.should_exit = True
    thread.join(20)


def parse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((fields["event"], json.loads(fields["data"])))
    return out


class Stream:
    """An SSE stream read as it comes: (event, data) pairs."""

    def __init__(self, lines):
        self.lines, self.seen = lines, []

    def __iter__(self):
        event = None
        for line in self.lines:
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                self.seen.append((event, json.loads(line[6:])))
                yield self.seen[-1]

    def count(self, rid=None):
        lines = [json.loads(d["line"]) for e, d in self.seen if e == "harness.stdout" and rid in (None, d["response"])]
        return max([x["n"] for x in lines if x.get("type") == "count"], default=0)


def idle(c, sid, timeout=30):
    deadline = time.monotonic() + timeout
    while (s := c.get(f"/sessions/{sid}").json())["status"] != "idle":
        assert time.monotonic() < deadline, s
        time.sleep(0.05)
    return s


# resources
def test_a_providers_key_is_never_returned(client, up):
    body = {"name": "up", "url": up.url + "/anthropic", "api": "anthropic-messages", "key": KEY}
    r = client.put("/providers/up", json=body)
    assert r.status_code == 200 and r.json() == {"name": "up", "url": up.url + "/anthropic", "api": "anthropic-messages"}
    assert KEY not in client.get("/providers").text and KEY not in client.get("/providers/up").text
    assert client.get("/providers").json() == [r.json()]
    assert client.delete("/providers/up").json() == {"deleted": "up"}
    assert client.get("/providers/up").status_code == 404 and client.delete("/providers/up").status_code == 404


def test_provider_refusals(client):
    good = {"url": "https://api.openai.com/v1", "api": "openai-chat", "key": KEY}
    assert client.put("/providers/x", json={**good, "name": "y"}).status_code == 400
    assert client.put("/providers/x", json={**good, "url": "https://api.openai.com"}).status_code == 400
    assert client.put("/providers/Bad_Name", json=good).status_code == 400
    r = client.put("/providers/x", json={"url": "https://api.openai.com/v1"})
    assert r.status_code == 422 and "detail" in r.json()


def test_a_harness_is_put_as_its_files_installed_and_shown_with_its_install(client, up):
    got = register(client, up)
    assert got["install"]["state"] == "ready" and got["interrupt"] == "steered" and "anthropic-messages" in got["apis"]
    assert got["files"]["adapter.py"] == (TEMPLATE / "adapter.py").read_text()
    assert [h["name"] for h in client.get("/harnesses").json()] == ["template"]
    assert "files" not in client.get("/harnesses").json()[0]
    assert client.delete("/harnesses/template").json() == {"deleted": "template"}
    assert client.get("/harnesses/template").status_code == 404 and client.delete("/harnesses/template").status_code == 404


def test_a_harness_that_fails_to_install_says_so_with_its_log(client, up):
    got = register(client, up, **{"install.sh": "echo cannot reach anything; exit 3\n"})
    assert got["install"]["state"] == "failed" and "cannot reach anything" in got["install"]["log"]
    r = client.post("/responses", json={"model": "template", "input": "count to 1"})
    assert r.status_code == 400 and "failed to install" in r.json()["detail"]


def test_harness_refusals(client):
    body = template_map()
    assert client.put("/harnesses/other", json=body).status_code == 400            # it names itself template
    assert client.put("/harnesses/template", json={**body, "../x": "y"}).status_code == 400
    assert client.put("/harnesses/template", json=template_map(lambda s: s.update(contract=9))).status_code == 400
    assert client.put("/harnesses/template", json={**body, "a": 1}).status_code == 422
    assert client.put("/harnesses/template", json=["not", "a", "map"]).status_code == 422
    assert client.get("/harnesses").json() == []


# responses
def test_a_response_in_the_responses_shape_with_everything_the_harness_did(client, template):
    blob = base64.b64encode(b"\x00\xffbinary").decode()
    body = {"model": "template/standin-7", "instructions": "be brief", "metadata": {"who": "test"},
            "input": [{"type": "input_text", "text": "count to 2"},
                      {"type": "input_file", "filename": "notes/a.txt", "file_data": "A\n"},
                      {"type": "input_file", "filename": "b.bin", "file_data": f"data:application/octet-stream;base64,{blob}"}]}
    r = client.post("/responses", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert r.headers["x-response-id"] == d["id"] and r.headers["x-session-id"] == d["harness"]["session"]
    assert (d["object"], d["status"], d["model"], d["instructions"]) == ("response", "completed", body["model"], "be brief")
    assert d["input"] == body["input"] and d["metadata"] == {"who": "test"} and d["previous_response_id"] is None
    assert d["output"][0]["content"][0]["text"] == "Counted to 2." and d["error"] is None
    assert d["usage"] == {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}
    h = d["harness"]
    assert (h["name"], h["provider"], h["exit_code"], h["stop"], h["steers"], h["undelivered"]) == \
        ("template", "up", 0, None, [], [])
    assert h["latency_s"] > 0 and h["resume"] and h["base"] and h["commit"] and h["cost_usd"] == 0.0
    assert h["usage"] == {"input_tokens": 3, "output_tokens": 2} and h["output"]["count"] == 2
    assert '"type": "count"' in h["stdout"] and h["stderr"] == "" and "+2" in h["diff"]
    assert h["changes"] == {"count.txt": "1\n2\n"}
    assert {"notes/a.txt", "b.bin", "count.txt"} <= set(h["files"])
    assert h["home"] == {f".standin/memory/{h['resume']}.md": "- count to 2\n"}
    loaded = next(json.loads(x) for x in h["stdout"].splitlines() if '"loaded"' in x)
    assert loaded["instructions"] == "be brief"


def test_the_stream_is_server_sent_events_in_order(client, template):
    with client.stream("POST", "/responses", json={"model": "template", "input": "count to 2", "stream": True}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        rid, sid = r.headers["x-response-id"], r.headers["x-session-id"]
        evs = parse(b"".join(r.iter_bytes()).decode())
    assert evs[0][0] == "response.created" and evs[0][1]["response"]["id"] == rid
    assert evs[0][1]["response"]["status"] == "in_progress" and evs[0][1]["response"]["harness"]["session"] == sid
    assert evs[-1][0] == "response.completed" and evs[-1][1]["response"]["status"] == "completed"
    assert {e for e, _ in evs[1:-1]} == {"harness.stdout"}
    counts = [json.loads(d["line"]) for _, d in evs[1:-1]]
    assert [x["n"] for x in counts if x["type"] == "count"] == [1, 2]
    assert [d["sequence_number"] for _, d in evs] == list(range(len(evs)))


def test_continuing_a_response_and_its_refusals(client, template, up):
    first = client.post("/responses", json={"model": "template", "input": "count to 1"}).json()
    second = client.post("/responses", json={"model": "template", "input": "count to 2",
                                             "previous_response_id": first["id"]}).json()
    assert second["previous_response_id"] == first["id"] and second["harness"]["session"] == first["harness"]["session"]
    assert second["harness"]["changes"] == {"count.txt": "1\n2\n"} and second["output"][0]["content"][0]["text"] == \
        "Counted to 2."
    r = client.post("/responses", json={"model": "template", "input": "x", "previous_response_id": "resp_0000000000000000"})
    assert r.status_code == 404
    register(client, up, name="other")
    r = client.post("/responses", json={"model": "other", "input": "x", "previous_response_id": first["id"]})
    assert r.status_code == 400 and "stays on" in r.json()["detail"]


def test_requests_refused_before_anything_runs(client, template):
    assert client.post("/responses", json={"model": "nope", "input": "x"}).status_code == 400
    assert client.post("/responses", json={"model": "template@nope", "input": "x"}).status_code == 400
    assert client.post("/responses", json={"model": "template", "input": ""}).status_code == 422
    assert client.post("/responses", json={"input": "x"}).status_code == 422
    files = [{"type": "input_text", "text": "x"}, {"type": "input_file", "filename": "a", "file_data": "data:;base64,@@"}]
    assert client.post("/responses", json={"model": "template", "input": files}).status_code == 422
    inside = [{"type": "input_text", "text": "x"}, {"type": "input_file", "filename": ".home/x", "file_data": "y"}]
    assert client.post("/responses", json={"model": "template", "input": inside}).status_code == 400
    assert client.get("/sessions").json() == {"object": "list", "data": []}


def test_sessions_are_listed_and_shown_with_every_response(client, template):
    first = client.post("/responses", json={"model": "template", "input": "count to 1"}).json()
    client.post("/responses", json={"model": "template", "input": "count to 2", "previous_response_id": first["id"]})
    sid = first["harness"]["session"]
    listed = client.get("/sessions").json()["data"]
    assert [s["id"] for s in listed] == [sid] and "responses" not in listed[0] and "token" not in listed[0]
    s = client.get(f"/sessions/{sid}").json()
    assert (s["object"], s["status"], s["harness"], s["provider"], s["interrupt"]) == \
        ("session", "idle", "template", "up", "steered")
    assert [r["output"][0]["content"][0]["text"] for r in s["responses"]] == ["Counted to 1.", "Counted to 2."]
    assert s["resume"] == s["responses"][-1]["harness"]["resume"] and s["interrupts"] == []
    assert client.get("/sessions/sess_0000000000000000").status_code == 404
    with client.stream("GET", f"/sessions/{sid}?stream=true") as r:
        assert r.status_code == 200 and b"".join(r.iter_bytes()) == b""         # idle: nothing to follow


# interrupt and stop
def test_interrupt_steers_a_steered_response_and_the_stream_shows_the_steer(live):
    with live.stream("POST", "/responses", json={"model": "template", "input": "count to 30", "stream": True}) as r:
        sid, stream, got = r.headers["x-session-id"], Stream(r.iter_lines()), None
        for event, data in stream:
            if event == "harness.stdout" and stream.count() == 2 and not got:
                got = live.post(f"/sessions/{sid}/interrupt", json={"input": "now count to 4"})
                assert got.status_code == 200 and got.json()["outcome"] == "steered"
                assert got.json()["response"]["status"] == "in_progress"
    kinds = [e for e, _ in stream.seen]
    assert kinds[0] == "response.created" and kinds[-1] == "response.completed"
    steer = kinds.index("harness.steer")
    assert "harness.stdout" in kinds[:steer] and "harness.stdout" in kinds[steer:]
    assert stream.seen[steer][1]["input"] == "now count to 4"
    done = stream.seen[-1][1]["response"]
    assert done["output"][0]["content"][0]["text"] == "Counted to 4." and done["harness"]["steers"][0]["input"] == \
        "now count to 4"
    assert live.get(f"/sessions/{sid}").json()["interrupts"][0]["outcome"] == "steered"


def test_interrupt_stops_and_continues_a_harness_that_takes_no_steers(live, up):
    register(live, up, name="patient", change=lambda s: s["run"].update(interrupt="continued"))
    first = live.post("/responses", json={"model": "patient", "input": "count to 1"}).json()
    sid = first["harness"]["session"]
    with live.stream("POST", "/responses", json={"model": "patient", "input": "count to 30", "stream": True,
                                                 "previous_response_id": first["id"]}) as r:
        rid, stream = r.headers["x-response-id"], Stream(r.iter_lines())
        for event, data in stream:
            if event == "harness.stdout" and stream.count(rid) == 3:
                break
    with live.stream("GET", f"/sessions/{sid}?stream=true") as follow:
        lines = follow.iter_lines()
        got = live.post(f"/sessions/{sid}/interrupt", json={"input": "count to 5"})
        seen = Stream(lines)
        list(seen)
    assert got.status_code == 200 and got.json()["outcome"] == "continued"
    new = got.json()["response"]
    assert new["status"] == "completed" and new["previous_response_id"] == rid
    assert new["output"][0]["content"][0]["text"] == "Counted to 5."
    kinds = [(e, d.get("response", {}).get("id") if isinstance(d.get("response"), dict) else d.get("response"))
             for e, d in seen.seen if e != "harness.stdout"]
    assert kinds == [("response.created", rid), ("response.completed", rid), ("session.interrupted", new["id"]),
                     ("response.created", new["id"]), ("response.completed", new["id"])]
    interrupted = next(d for e, d in seen.seen if e == "session.interrupted")
    assert (interrupted["outcome"], interrupted["from"], interrupted["input"]) == ("continued", rid, "count to 5")
    assert live.get(f"/sessions/{sid}").json()["responses"][1]["status"] == "cancelled"


def test_interrupting_an_idle_session_continues_it_and_can_stream(client, template):
    first = client.post("/responses", json={"model": "template", "input": "count to 1"}).json()
    sid = first["harness"]["session"]
    got = client.post(f"/sessions/{sid}/interrupt", json={"input": "count to 2"})
    assert got.json()["outcome"] == "continued" and got.json()["response"]["previous_response_id"] == first["id"]
    with client.stream("POST", f"/sessions/{sid}/interrupt", json={"input": "count to 3", "stream": True}) as r:
        assert r.headers["x-interrupt-outcome"] == "continued"
        evs = parse(b"".join(r.iter_bytes()).decode())
    assert evs[0][0] == "response.created" and evs[-1][1]["response"]["output"][0]["content"][0]["text"] == \
        "Counted to 3."
    assert client.post(f"/sessions/{sid}/interrupt", json={"input": ""}).status_code == 422
    assert client.post("/sessions/sess_0000000000000000/interrupt", json={"input": "x"}).status_code == 404


def test_stop_is_graceful_a_kill_when_it_cant_wait_and_idle_when_nothing_runs(live):
    outcomes = []
    for body in ({}, {"timeout_s": 0}):
        with live.stream("POST", "/responses", json={"model": "template", "input": "count to 30", "stream": True}) as r:
            sid, stream, got = r.headers["x-session-id"], Stream(r.iter_lines()), None
            for event, _ in stream:
                if event == "harness.stdout" and stream.count() == 2 and not got:
                    got = live.post(f"/sessions/{sid}/stop", json=body)
                    outcomes.append((got.json()["outcome"], got.json()["session"]["status"],
                                     got.json()["session"]["responses"][-1]["harness"]["stop"]))
    assert outcomes == [("stopped", "idle", "stopped"), ("killed", "idle", "killed")]
    assert live.post(f"/sessions/{sid}/stop").json()["outcome"] == "idle"
    assert live.post("/sessions/sess_0000000000000000/stop").status_code == 404
    assert live.post(f"/sessions/{sid}/stop", json={"timeout_s": -1}).status_code == 422


def test_one_response_at_a_time_per_session(live):
    first = live.post("/responses", json={"model": "template", "input": "count to 1"}).json()
    with live.stream("POST", "/responses", json={"model": "template", "input": "count to 3", "stream": True,
                                                 "previous_response_id": first["id"]}) as r:
        busy = live.post("/responses", json={"model": "template", "input": "x", "previous_response_id": first["id"]})
        assert busy.status_code == 409 and "interrupt" in busy.json()["detail"]
        list(r.iter_lines())


def test_a_response_outlives_its_client(live):
    with live.stream("POST", "/responses", json={"model": "template", "input": "count to 3", "stream": True}) as r:
        sid = r.headers["x-session-id"]
        assert next(r.iter_lines()) == "event: response.created"
    s = idle(live, sid)                                                   # the client left; the response did not
    assert s["responses"][0]["status"] == "completed" and s["responses"][0]["harness"]["changes"] == \
        {"count.txt": "1\n2\n3\n"}


def test_artifacts_are_live_while_it_runs(live):
    with live.stream("POST", "/responses", json={"model": "template", "input": "count to 30", "stream": True}) as r:
        sid, stream, now = r.headers["x-session-id"], Stream(r.iter_lines()), None
        for event, _ in stream:
            if event == "harness.stdout" and stream.count() == 2 and not now:
                now = live.get(f"/sessions/{sid}").json()["responses"][0]
                live.post(f"/sessions/{sid}/stop")
    assert now["status"] == "in_progress" and now["harness"]["changes"]["count.txt"].startswith("1\n2\n")
    assert '"n": 2' in now["harness"]["stdout"] and now["harness"]["output"]["status"] == "running"
    assert "count.txt" in now["harness"]["files"] and now["harness"]["home"]


def test_steers_the_harness_didnt_take_continue_the_session(live, up):
    register(live, up, name="deaf", **{"adapter.py": DEAF})
    with live.stream("POST", "/responses", json={"model": "deaf", "input": "count to 3", "stream": True}) as r:
        sid, stream = r.headers["x-session-id"], Stream(r.iter_lines())
        for event, _ in stream:
            if event == "harness.stdout" and stream.count() == 1:
                assert live.post(f"/sessions/{sid}/interrupt", json={"input": "count to 5"}).json()["outcome"] == \
                    "steered"
                break
    s = idle(live, sid)
    first, second = s["responses"]
    assert first["harness"]["undelivered"] == ["count to 5"] and second["previous_response_id"] == first["id"]
    assert second["input"] == "count to 5" and second["output"][0]["content"][0]["text"] == "Counted to 5."


# the OpenAI SDK
def test_the_openai_sdk_creates_streams_and_continues_unchanged(live):
    from openai import OpenAI
    sdk = OpenAI(base_url=str(live.base_url), api_key="unused", max_retries=0)
    first = sdk.responses.create(model="template", input="count to 1")
    assert first.status == "completed" and first.output_text == "Counted to 1."
    second = sdk.responses.create(model="template", input=[{"role": "user", "content": "count to 2"}],
                                  previous_response_id=first.id, instructions="be brief")
    assert second.previous_response_id == first.id and second.output_text == "Counted to 2."
    kinds, last = [], None
    for event in sdk.responses.create(model="template", input="count to 2", stream=True):
        kinds.append(event.type)
        last = event
    assert kinds[0] == "response.created" and kinds[-1] == "response.completed" and "harness.stdout" in kinds
    assert last.response.output_text == "Counted to 2."


# the server
def test_a_restart_closes_what_was_in_flight(sessions):
    sessions.store.put("sess_00000000000000bb", Session(
        id="sess_00000000000000bb", harness="template", provider="up", model="", interrupt="steered",
        workspace=str(sessions.workspaces / "sess_00000000000000bb"), token="sk-hi-x", status="active",
        responses=["resp_00000000000000bb"]))
    sessions.records.put("resp_00000000000000bb", ResponseRecord(
        id="resp_00000000000000bb", session="sess_00000000000000bb", model="template", harness="template",
        provider="up", request={"input": "x"}))
    with TestClient(create_app(sessions)) as c:
        s = c.get("/sessions/sess_00000000000000bb").json()
    assert s["status"] == "idle" and s["responses"][0]["status"] == "failed"
    assert s["responses"][0]["error"]["code"] == "server_restarted"


def test_the_server_will_not_start_without_git(sessions, monkeypatch):
    from harness_interface import workspace
    monkeypatch.setattr(workspace.shutil, "which", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="git is required"):
        with TestClient(create_app(sessions)):
            pass


def test_settings_come_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("HI_HOST", "0.0.0.0")
    monkeypatch.setenv("HI_PORT", "9001")
    monkeypatch.setenv("HI_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("HI_RUNTIME", "local")
    monkeypatch.setenv("HI_CA_FILE", str(tmp_path / "ca.pem"))
    s = Settings.from_env()
    assert (s.host, s.port, s.data_dir, s.runtime, s.ca_file) == ("0.0.0.0", 9001, tmp_path / "d", "local",
                                                                  tmp_path / "ca.pem")
    assert not build(s).placement.docker and build(s).placement.owner == owner_of(tmp_path / "d")
    monkeypatch.setenv("HI_RUNTIME", "podman")
    with pytest.raises(ValueError):
        Settings.from_env()
    monkeypatch.delenv("HI_RUNTIME")
    assert Settings.from_env().runtime == "docker" and build(Settings.from_env()).placement.docker


def test_no_key_is_in_anything_served_kept_or_logged(client, template, tmp_path):
    served = [client.post("/responses", json={"model": "template", "input": "count to 1"}).text]
    with client.stream("POST", "/responses", json={"model": "template", "input": "count to 1", "stream": True}) as r:
        served.append(b"".join(r.iter_bytes()).decode())
    sid = json.loads(served[0])["harness"]["session"]
    served += [client.get(p).text for p in ("/sessions", f"/sessions/{sid}", "/providers", "/providers/up",
                                            "/harnesses", "/harnesses/template")]
    assert '"status": 200' in served[0].replace('\\"', '"')               # it did reach its provider
    assert not any(KEY in text for text in served)
    for p in (tmp_path / "data").rglob("*"):
        if p.is_file() and "providers" not in p.parts:
            assert KEY.encode() not in p.read_bytes(), p
