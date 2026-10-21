"""Layer 6: every route under a real principal. The admin key creates an org; owners register and
members request; one org never sees another's; the Responses shape, streamed and not, background
and cancelled; sessions, traces and archives; keys revoked."""
import io
import json
import tarfile
import time

import pytest
from fastapi.testclient import TestClient

from fakes import FakeRuntimes, archive
from harness_interface.api.app import Service, create_app
from harness_interface.api.config import Settings

ADMIN = "admin-" + "x" * 20


@pytest.fixture
def client(tmp_path, vault):
    service = Service(Settings(data_dir=tmp_path / "data", admin_key=ADMIN), vault)
    service.sessions.runtimes = FakeRuntimes()
    with TestClient(create_app(service)) as c:
        yield c


def auth(key):
    return {"Authorization": f"Bearer {key}"}


def org(c, name="acme", owner="chase"):
    r = c.post("/v1/orgs", json={"name": name, "owner": owner}, headers=auth(ADMIN))
    assert r.status_code == 200, r.text
    return r.json()["key"]["secret"]


def ready(c, key):
    """Provider, sandbox and harness registered; a member's key."""
    assert c.put("/v1/providers/prov", json={"url": "https://api.example", "api": "openai-chat", "key": "sk-real"},
                 headers=auth(key)).status_code == 200
    assert c.put("/v1/sandboxes/box", json={"image": "img"}, headers=auth(key)).status_code == 200
    r = c.put("/v1/harnesses/cc", content=archive(), headers=auth(key))
    assert r.status_code == 200, r.text
    assert c.post("/v1/members", json={"name": "dev"}, headers=auth(key)).status_code == 200
    return c.post("/v1/members/dev/keys", json={"label": "ci"}, headers=auth(key)).json()["secret"]


def test_auth_and_roles(client):
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers=auth("hi_nope")).status_code == 401
    assert client.get("/v1/me", headers=auth(ADMIN)).status_code == 403
    assert client.post("/v1/orgs", json={"name": "acme", "owner": "chase"}).status_code == 401
    owner = org(client)
    assert client.post("/v1/orgs", json={"name": "x", "owner": "y"}, headers=auth(owner)).status_code == 403
    assert client.get("/v1/orgs", headers=auth(ADMIN)).json()["data"][0]["name"] == "acme"
    assert client.get("/v1/me", headers=auth(owner)).json()["role"] == "owner"
    dev = ready(client, owner)
    assert client.get("/v1/me", headers=auth(dev)).json() == {"org": "acme", "name": "dev", "role": "member",
                                                              "created": client.get("/v1/me", headers=auth(dev)).json()["created"]}
    assert client.put("/v1/providers/x", json={"url": "https://x", "api": "openai-chat", "key": "k"}, headers=auth(dev)).status_code == 403
    assert client.put("/v1/sandboxes/x", json={"image": "i"}, headers=auth(dev)).status_code == 403
    assert client.put("/v1/harnesses/x", content=archive(), headers=auth(dev)).status_code == 403
    assert client.post("/v1/members", json={"name": "z"}, headers=auth(dev)).status_code == 403
    assert client.post("/v1/members/chase/keys", json={}, headers=auth(dev)).status_code == 403
    assert client.get("/v1/providers", headers=auth(dev)).json()["data"] == [{"name": "prov", "url": "https://api.example", "api": "openai-chat"}]
    assert client.get("/v1/harnesses/cc", headers=auth(dev)).json()["defaults"]["model"] == "m1"
    # keys: a member's own, revoked
    mine = client.post("/v1/members/dev/keys", json={"label": "two"}, headers=auth(dev)).json()
    assert [k["label"] for k in client.get("/v1/keys", headers=auth(dev)).json()["data"]] == ["ci", "two"]
    assert len(client.get("/v1/keys", headers=auth(owner)).json()["data"]) == 3
    assert client.delete(f"/v1/keys/{mine['id']}", headers=auth(dev)).json()["revoked"] is True
    assert client.get("/v1/me", headers=auth(mine["secret"])).status_code == 401
    assert client.delete(f"/v1/keys/{mine['id']}", headers=auth(org(client, "other", "eve"))).status_code == 404


def test_registration_refusals(client):
    owner = org(client)
    assert client.put("/v1/providers/p", json={"url": "http://x", "api": "openai-chat", "key": "k"}, headers=auth(owner)).status_code == 400
    assert client.put("/v1/sandboxes/s", json={}, headers=auth(owner)).status_code == 400
    r = client.put("/v1/harnesses/h", content=archive({"request.sh": None}), headers=auth(owner))
    assert r.status_code == 400 and "request.sh is missing" in r.json()["detail"]
    assert client.put("/v1/harnesses/h", content=b"", headers=auth(owner)).status_code == 400
    assert client.get("/v1/harnesses/h", headers=auth(owner)).status_code == 404
    assert client.delete("/v1/providers/none", headers=auth(owner)).status_code == 404
    assert client.put("/v1/providers/Bad", json={"url": "https://x", "api": "openai-chat", "key": "k"}, headers=auth(owner)).status_code == 400


def test_a_response(client):
    dev = ready(client, org(client))
    r = client.post("/v1/responses", json={"model": "cc", "input": "hello", "metadata": {"model": "m9", "team": "a"}},
                    headers=auth(dev))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["object"] == "response" and body["status"] == "completed" and body["model"] == "cc"
    out, err = body["output"]
    assert "prompt=hello turn=1 model=m9" in out["content"][0]["text"] and err["content"][0]["text"] == "stderr line\n"
    assert body["metadata"]["team"] == "a" and body["metadata"]["exit_code"] == "0"
    sid = body["metadata"]["session_id"]
    assert r.headers["X-Session-Id"] == sid
    assert client.get(f"/v1/responses/{body['id']}", headers=auth(dev)).json() == body
    s = client.get(f"/v1/sessions/{sid}", headers=auth(dev)).json()
    assert s["status"] == "idle" and s["responses"] == [body["id"]] and s["harness"] == "cc"
    assert [x["id"] for x in client.get("/v1/sessions", headers=auth(dev)).json()["data"]] == [sid]
    again = client.post("/v1/responses", json={"model": "cc", "input": "more", "previous_response_id": body["id"]},
                        headers=auth(dev)).json()
    assert again["metadata"]["turn"] == "2" and again["previous_response_id"] == body["id"]
    trace = client.get(f"/v1/sessions/{sid}/trace", headers=auth(dev)).json()["data"]
    assert [t["kind"] for t in trace] == ["request", "response", "request", "response"]
    assert trace[1]["body"]["output"][0]["content"][0]["text"] == out["content"][0]["text"]
    assert trace[0]["body"] == {"model": "cc", "input": "hello", "store": True, "stream": False, "background": False,
                                "metadata": {"model": "m9", "team": "a"}}
    tar = client.get(f"/v1/sessions/{sid}/archive", headers=auth(dev))
    assert tar.headers["content-type"] == "application/gzip"
    with tarfile.open(fileobj=io.BytesIO(tar.content)) as t:
        assert "./out.txt" in t.getnames()
    assert client.delete(f"/v1/sessions/{sid}", headers=auth(dev)).json() == {"deleted": sid}
    assert client.get(f"/v1/sessions/{sid}", headers=auth(dev)).status_code == 404


def test_streamed_and_background(client):
    dev = ready(client, org(client))
    with client.stream("POST", "/v1/responses", json={"model": "cc", "input": "hi", "stream": True},
                       headers=auth(dev)) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "response.created" and kinds[-1] == "response.completed"
    assert "".join(e["delta"] for e in events if e["type"] == "response.output_text.delta" and e["output_index"] == 0) \
        == events[-1]["response"]["output"][0]["content"][0]["text"]
    bg = client.post("/v1/responses", json={"model": "cc", "input": "bg", "background": True}, headers=auth(dev)).json()
    assert bg["status"] == "in_progress"
    for _ in range(100):
        got = client.get(f"/v1/responses/{bg['id']}", headers=auth(dev)).json()
        if got["status"] != "in_progress":
            break
        time.sleep(0.05)
    assert got["status"] == "completed" and "prompt=bg" in got["output"][0]["content"][0]["text"]
    with client.stream("GET", f"/v1/responses/{bg['id']}?stream=true", headers=auth(dev)) as r:
        replay = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
    assert replay[-1]["type"] == "response.completed"


def test_cancel_busy_and_interrupt(client):
    owner = org(client)
    dev = ready(client, owner)
    assert client.put("/v1/harnesses/slow", content=archive({"request.sh": "#!/bin/bash\necho go\nsleep 30\n"}),
                      headers=auth(owner)).status_code == 200
    bg = client.post("/v1/responses", json={"model": "slow", "input": "x", "background": True}, headers=auth(dev)).json()
    sid = bg["metadata"]["session_id"]
    time.sleep(0.3)
    assert client.get(f"/v1/sessions/{sid}", headers=auth(dev)).json()["status"] == "running"
    busy = client.post("/v1/responses", json={"model": "slow", "input": "y", "previous_response_id": bg["id"]}, headers=auth(dev))
    assert busy.status_code == 409
    assert client.post(f"/v1/sessions/{sid}/interrupt", json={"input": "left"}, headers=auth(dev)).status_code == 409
    assert client.delete(f"/v1/sessions/{sid}", headers=auth(dev)).status_code == 409
    done = client.post(f"/v1/responses/{bg['id']}/cancel", headers=auth(dev)).json()
    assert done["status"] == "cancelled" and done["output"][0]["content"][0]["text"] == "go\n"
    assert done["incomplete_details"] is None


def test_orgs_do_not_see_each_other(client):
    dev = ready(client, org(client))
    r = client.post("/v1/responses", json={"model": "cc", "input": "hello"}, headers=auth(dev)).json()
    eve = org(client, "other", "eve")
    assert client.get("/v1/harnesses", headers=auth(eve)).json()["data"] == []
    assert client.get(f"/v1/responses/{r['id']}", headers=auth(eve)).status_code == 404
    assert client.get(f"/v1/sessions/{r['metadata']['session_id']}", headers=auth(eve)).status_code == 404
    assert client.get("/v1/sessions", headers=auth(eve)).json()["data"] == []
    assert client.post("/v1/responses", json={"model": "cc", "input": "x"}, headers=auth(eve)).status_code == 404


def test_openai_sdk_client(client):
    """The official SDK, unchanged, against the server."""
    openai = pytest.importorskip("openai")
    dev = ready(client, org(client))
    sdk = openai.OpenAI(api_key=dev, base_url=str(client.base_url) + "/v1", http_client=client)
    r = sdk.responses.create(model="cc", input="from the sdk", metadata={"model": "m3"})
    assert r.status == "completed" and "prompt=from the sdk turn=1 model=m3" in r.output_text
    assert "stderr line" in r.output_text
    parts = [ev for ev in sdk.responses.create(model="cc", input="streamed", stream=True)]
    assert parts[-1].type == "response.completed" and parts[-1].response.status == "completed"
