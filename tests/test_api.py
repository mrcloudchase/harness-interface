"""Layer 6, end to end without Docker: the API with an in-process worker on a fake node, over ASGI.
Sign-up, registration, a turn that runs request.sh and response.sh, continuation from a snapshot,
streaming, background, cancel, steer, stateless, archive, trace, the deployer's view, tenants apart,
and the official OpenAI SDK unchanged."""
import asyncio
import io
import json
import tarfile

import httpx
import pytest

from fakes import FakeNode, archive, RESPONSE_SH
from harnessgateway.api.app import Service, create_app
from harnessgateway.api.config import Settings
from harnessgateway.worker import Worker

SLOW = """#!/usr/bin/env bash
echo started
trap 'echo "steer=$(cat "$HG_DIR/interrupt")"; exit 0' USR1
trap 'echo stopping; exit 0' TERM
sleep 30 & wait $!
"""


@pytest.fixture
def platform(tmp_path, vault, monkeypatch):
    monkeypatch.setenv("HG_CATALOG_DIR", str(tmp_path / "catalog"))
    from harnessgateway.harness import unpack
    unpack(archive(description="shipped"), tmp_path / "catalog" / "demo")
    settings = Settings(data_dir=tmp_path / "data", public_url="http://api.test", signup="open", join_token="jt",
                        deployer_key="hd_deployer")
    service = Service(settings, vault)
    app = create_app(service)
    transport = httpx.ASGITransport(app=app)
    node = FakeNode()
    worker = Worker("http://api.test", node, tmp_path / "cache", name="w1", slots=2, version="t", join_token="jt", transport=transport)
    return app, transport, worker, node


def run(platform, scenario):
    app, transport, worker, node = platform

    async def go():
        task = asyncio.create_task(worker.run())
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test", timeout=60) as c:
            try:
                return await scenario(c, node)
            finally:
                worker.stopping = True
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    return asyncio.run(go())


def auth(key):
    return {"Authorization": f"Bearer {key}"}


async def signup(c, tenant="acme", owner="chase"):
    """A tenant with its owner's key, the deployer's way (sign-up proper is an account: test_accounts)."""
    r = await c.post("/v1/tenants", json={"name": tenant, "owner": owner}, headers=auth("hd_deployer"))
    assert r.status_code == 200, r.text
    return r.json()["key"]["secret"]


async def ready(c, key, package=None):
    assert (await c.put("/v1/providers/prov", json={"url": "https://api.example/v1", "api": "openai-chat", "key": "sk-real"}, headers=auth(key))).status_code == 200
    r = await c.put("/v1/harnesses/cc", content=package or archive({"response.sh": RESPONSE_SH}), headers=auth(key))
    assert r.status_code == 200, r.text
    assert (await c.post("/v1/members", json={"name": "dev"}, headers=auth(key))).status_code == 200
    return (await c.post("/v1/members/dev/keys", json={"label": "ci"}, headers=auth(key))).json()["secret"]


async def poll(c, key, rid, timeout=30):
    for _ in range(int(timeout / 0.2)):
        got = (await c.get(f"/v1/responses/{rid}", headers=auth(key))).json()
        if got["status"] != "in_progress":
            return got
        await asyncio.sleep(0.2)
    raise AssertionError("still running")


def test_signup_auth_and_registration(platform):
    async def scenario(c, node):
        assert (await c.get("/healthz")).json()["signup"] == "open"
        owner = await signup(c)
        assert (await c.post("/v1/tenants", json={"name": "acme", "owner": "x"}, headers=auth("hd_deployer"))).status_code == 409
        assert (await c.get("/v1/me")).status_code == 401
        assert (await c.get("/v1/me", headers=auth("hg_nope"))).status_code == 401
        assert (await c.get("/v1/me", headers=auth("hd_deployer"))).status_code == 403
        assert (await c.get("/v1/tenants", headers=auth(owner))).status_code == 403
        dev = await ready(c, owner)
        me = (await c.get("/v1/me", headers=auth(dev))).json()
        assert me["role"] == "member" and me["limits"]["max_runs"] == 4
        assert (await c.put("/v1/providers/x", json={"url": "https://x.example", "api": "openai-chat", "key": "k"}, headers=auth(dev))).status_code == 403
        assert (await c.put("/v1/providers/x", json={"url": "https://10.0.0.1", "api": "openai-chat", "key": "k"}, headers=auth(owner))).status_code == 400
        assert (await c.get("/v1/providers", headers=auth(dev))).json()["data"] == [{"name": "prov", "url": "https://api.example/v1", "api": "openai-chat"}]
        h = (await c.get("/v1/harnesses/cc", headers=auth(dev))).json()
        assert h["defaults"]["model"] == "m1" and h["run"]["egress"] == ["git.example"] and len(h["versions"]) == 1
        bad = await c.put("/v1/harnesses/h", content=archive({"request.sh": None}), headers=auth(owner))
        assert bad.status_code == 400 and "request.sh is missing" in bad.json()["detail"]
        assert (await c.get("/v1/catalog", headers=auth(dev))).json()["data"][0]["name"] == "demo"
        fork = await c.put("/v1/harnesses/mine", json={"catalog": "demo"}, headers=auth(owner))
        assert fork.status_code == 200 and fork.json()["description"] == "shipped"
        mine = (await c.post("/v1/members/dev/keys", json={"label": "two"}, headers=auth(dev))).json()
        assert [k["label"] for k in (await c.get("/v1/keys", headers=auth(dev))).json()["data"]] == ["ci", "two"]
        assert (await c.delete(f"/v1/keys/{mine['id']}", headers=auth(dev))).json()["revoked"] is True
        assert (await c.get("/v1/me", headers=auth(mine["secret"]))).status_code == 401
    run(platform, scenario)


def test_a_turn_and_its_session(platform):
    async def scenario(c, node):
        owner = await signup(c)
        dev = await ready(c, owner)
        r = await c.post("/v1/responses", json={"model": "cc/prov/m9", "input": "hello", "instructions": "be brief",
                                                 "metadata": {"team": "a"}}, headers=auth(dev))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed" and body["model"] == "cc/prov/m9", body
        text = body["output"][0]["content"][0]["text"]
        assert text.startswith("shaped: outcome=exited exit=0 prompt=hello turn=1 model=m9 key=sk-hg-")   # response.sh decided
        assert "url=http://hg-provider:8080/v1 ins=be brief" in text
        assert body["metadata"]["team"] == "a" and body["metadata"]["exit_code"] == "0" and node.installs == 1
        sid = body["metadata"]["session_id"]
        detail = (await c.get(f"/v1/responses/{body['id']}?detail=true", headers=auth(dev))).json()
        assert "org=from-org" in detail["stdout"] and "user=from-user" in detail["stdout"] and "project=from-project" in detail["stdout"]
        assert "request=hello" in detail["stdout"] and detail["stderr"] == "stderr line\n"
        again = await c.post("/v1/responses", json={"model": "cc", "input": "more", "previous_response_id": body["id"]}, headers=auth(dev))
        assert again.json()["metadata"]["turn"] == "2" and "turn=2 model=m1" in again.json()["output"][0]["content"][0]["text"]
        tar = await c.get(f"/v1/sessions/{sid}/archive", headers=auth(dev))
        with tarfile.open(fileobj=io.BytesIO(tar.content)) as t:
            assert t.extractfile("./out.txt").read() == b"more\n"             # the workspace persisted across turns
        trace = (await c.get(f"/v1/sessions/{sid}/trace", headers=auth(dev))).json()["data"]
        assert [t["kind"] for t in trace] == ["request", "response", "request", "response"]
        assert trace[0]["body"] == {"model": "cc/prov/m9", "input": "hello", "instructions": "be brief", "store": True,
                                    "stream": False, "background": False, "metadata": {"team": "a"}}
        s = (await c.get(f"/v1/sessions/{sid}", headers=auth(dev))).json()
        assert s["status"] == "idle" and len(s["responses"]) == 2
        assert (await c.post("/v1/responses", json={"model": "cc/prov", "input": "x"}, headers=auth(dev))).status_code == 422
        assert (await c.delete(f"/v1/sessions/{sid}", headers=auth(dev))).json() == {"deleted": sid}
        assert (await c.get(f"/v1/sessions/{sid}", headers=auth(dev))).status_code == 404
    run(platform, scenario)


def test_files_stream_background_stateless(platform):
    async def scenario(c, node):
        owner = await signup(c)
        dev = await ready(c, owner)
        r = await c.post("/v1/responses", json={"model": "cc", "input": [
            {"type": "input_text", "text": "files"}, {"type": "input_file", "filename": "README.md", "file_data": "mine"}]}, headers=auth(dev))
        detail = (await c.get(f"/v1/responses/{r.json()['id']}?detail=true", headers=auth(dev))).json()
        assert "project=mine" in detail["stdout"]                               # a request's file wins over the seed
        async with c.stream("POST", "/v1/responses", json={"model": "cc", "input": "hi", "stream": True}, headers=auth(dev)) as s:
            assert s.status_code == 200 and s.headers["content-type"].startswith("text/event-stream")
            events = [json.loads(line[6:]) async for line in s.aiter_lines() if line.startswith("data: ")]
        kinds = [e["type"] for e in events]
        assert kinds[0] == "response.created" and kinds[-1] == "response.completed"
        assert "".join(e["delta"] for e in events if e["type"] == "response.output_text.delta").startswith("prompt=hi")
        assert events[-1]["response"]["output"][0]["content"][0]["text"].startswith("shaped")
        bg = (await c.post("/v1/responses", json={"model": "cc", "input": "bg", "background": True}, headers=auth(dev))).json()
        assert bg["status"] == "in_progress"
        got = await poll(c, dev, bg["id"])
        assert got["status"] == "completed" and "prompt=bg" in got["output"][0]["content"][0]["text"]
        stateless = (await c.post("/v1/responses", json={"model": "cc", "input": "once", "store": False}, headers=auth(dev))).json()
        sid = stateless["metadata"]["session_id"]
        assert (await c.get(f"/v1/sessions/{sid}", headers=auth(dev))).json()["stored"] is False
        assert (await c.get(f"/v1/sessions/{sid}/archive", headers=auth(dev))).status_code == 404
        assert (await c.post("/v1/responses", json={"model": "cc", "input": "x", "previous_response_id": stateless["id"]}, headers=auth(dev))).status_code == 400
    run(platform, scenario)


def test_cancel_steer_and_busy(platform):
    async def scenario(c, node):
        owner = await signup(c)
        dev = await ready(c, owner)
        assert (await c.put("/v1/harnesses/slow", content=archive({"request.sh": SLOW}), headers=auth(owner))).status_code == 200
        bg = (await c.post("/v1/responses", json={"model": "slow", "input": "x", "background": True}, headers=auth(dev))).json()
        sid = bg["metadata"]["session_id"]
        for _ in range(100):
            if "started" in (await c.get(f"/v1/responses/{bg['id']}?detail=true", headers=auth(dev))).json()["stdout"]:
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("the running turn's output was not visible on ?detail=true")
        assert (await c.get(f"/v1/sessions/{sid}", headers=auth(dev))).json()["status"] == "running"
        assert (await c.post("/v1/responses", json={"model": "slow", "input": "y", "previous_response_id": bg["id"]}, headers=auth(dev))).status_code == 409
        assert (await c.delete(f"/v1/sessions/{sid}", headers=auth(dev))).status_code == 409
        assert (await c.post(f"/v1/sessions/{sid}/interrupt", json={"input": "left"}, headers=auth(dev))).status_code == 200
        steered = await poll(c, dev, bg["id"])
        assert steered["status"] == "completed" and "steer=left" in steered["output"][0]["content"][0]["text"], steered
        bg = (await c.post("/v1/responses", json={"model": "slow", "input": "x", "previous_response_id": steered["id"], "background": True}, headers=auth(dev))).json()
        for _ in range(100):
            if "started" in (await c.get(f"/v1/responses/{bg['id']}?detail=true", headers=auth(dev))).json()["stdout"]:
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("the running turn's output was not visible on ?detail=true")
        done = (await c.post(f"/v1/responses/{bg['id']}/cancel", headers=auth(dev))).json()
        assert done["status"] == "cancelled" and "stopping" in done["output"][0]["content"][0]["text"], done
        trace = [t["kind"] for t in (await c.get(f"/v1/sessions/{sid}/trace", headers=auth(dev))).json()["data"]]
        assert trace == ["request", "interrupt", "response", "request", "cancel", "response"]
    run(platform, scenario)


def test_deployer_and_tenants_apart(platform):
    async def scenario(c, node):
        owner = await signup(c)
        dev = await ready(c, owner)
        r = (await c.post("/v1/responses", json={"model": "cc", "input": "hello"}, headers=auth(dev))).json()
        d = auth("hd_deployer")
        tenants = (await c.get("/v1/tenants", headers=d)).json()["data"]
        assert tenants[0]["name"] == "acme" and tenants[0]["usage"]["turns"] == 1 and tenants[0]["usage"]["seconds"] >= 0  # a fast turn rounds to 0.0
        usage = (await c.get("/v1/usage?days=30", headers=d)).json()
        assert usage["totals"]["turns"] == 1 and len(usage["daily"]) == 30 and usage["daily"][-1]["turns"] == 1
        assert usage["tenants"] == [{"tenant": "acme", **usage["totals"]}] and usage["harnesses"][0]["harness"] == "cc"
        assert usage["statuses"]["completed"] == 1 and (await c.get("/v1/usage", headers=d)).json()["totals"]["turns"] == 1
        assert (await c.get("/v1/usage", headers=auth(owner))).status_code == 403
        fleet = (await c.get("/v1/fleet", headers=d)).json()
        assert fleet["tenants"] == 1 and fleet["workers"] == 1 and fleet["slots"] == 2
        made = (await c.post("/v1/tenants", json={"name": "globex", "owner": "eve", "limits": {"max_runs": 1}}, headers=d)).json()
        eve = made["key"]["secret"]
        assert (await c.get("/v1/harnesses", headers=auth(eve))).json()["data"] == []
        assert (await c.get(f"/v1/responses/{r['id']}", headers=auth(eve))).status_code == 404
        assert (await c.get(f"/v1/sessions/{r['metadata']['session_id']}", headers=auth(eve))).status_code == 404
        assert (await c.post("/v1/responses", json={"model": "cc", "input": "x"}, headers=auth(eve))).status_code == 404
        assert (await c.patch("/v1/tenants/acme", json={"status": "suspended"}, headers=d)).json()["status"] == "suspended"
        assert (await c.get("/v1/me", headers=auth(dev))).status_code == 401
        assert (await c.patch("/v1/tenants/acme", json={"status": "active", "limits": {"cpus": 1}}, headers=d)).status_code == 200
        assert (await c.get("/v1/me", headers=auth(dev))).json()["limits"]["cpus"] == 1
        workers = (await c.get("/v1/workers", headers=d)).json()["data"]
        assert workers[0]["name"] == "w1" and workers[0]["alive"]
        assert (await c.delete("/v1/tenants/globex", headers=d)).json() == {"deleted": "globex"}
        assert (await c.get("/v1/me", headers=auth(eve))).status_code == 401
    run(platform, scenario)


def test_openai_sdk_client(platform):
    openai = pytest.importorskip("openai")

    async def scenario(c, node):
        owner = await signup(c)
        dev = await ready(c, owner)
        sdk = openai.AsyncOpenAI(api_key=dev, base_url="http://api.test/v1", http_client=c)
        r = await sdk.responses.create(model="cc/prov/m3", input="from the sdk")
        assert r.status == "completed" and r.output_text.startswith("shaped: outcome=exited exit=0 prompt=from the sdk turn=1 model=m3")
        assert r.model == "cc/prov/m3"
        last = None
        async for ev in await sdk.responses.create(model="cc", input="streamed", stream=True):
            last = ev
        assert last.type == "response.completed" and last.response.status == "completed"
    run(platform, scenario)


# accounts: the app's sign-in, over the same routes
def test_accounts_sign_up_invite_switch_and_the_cookie_on_member_routes(platform):
    async def scenario(c, node):
        assert (await c.get("/auth/providers")).json() == {"signup": "open", "password": True, "mail": False, "github": False, "google": False}
        assert (await c.get("/auth/me")).status_code == 401
        assert (await c.post("/auth/signup", json={"email": "chase@example.com", "password": "short"})).status_code == 400
        r = await c.post("/auth/signup", json={"email": "Chase@Example.com", "password": "correct horse", "name": "Chase"})
        assert r.status_code == 201, r.text
        me = r.json()
        assert me["account"]["email"] == "chase@example.com" and me["account"]["verified"] and me["account"]["has_password"]
        assert me["current"] == {**me["current"], "tenant": "chase", "member": "chase", "role": "owner"}   # a tenant of its own, named after it
        assert "hg_session" in c.cookies
        assert (await c.post("/auth/signup", json={"email": "chase@example.com", "password": "correct horse"})).status_code == 409
        # the cookie is a member's credential on every member route; the deployer's routes still want the key
        assert (await c.get("/v1/me")).json()["name"] == "chase"
        assert (await c.put("/v1/providers/prov", json={"url": "https://api.example/v1", "api": "openai-chat", "key": "sk-real"})).status_code == 200
        assert (await c.get("/v1/fleet")).status_code == 401
        # an owner invites an email; the account that signs up with it joins as a member, not with a tenant of its own
        assert (await c.post("/v1/invites", json={"email": "dev@example.com", "role": "member"})).status_code == 200
        assert [i["email"] for i in (await c.get("/v1/invites")).json()["data"]] == ["dev@example.com"]
        dev = httpx.AsyncClient(transport=c._transport, base_url="http://api.test")
        async with dev:
            r = await dev.post("/auth/signup", json={"email": "dev@example.com", "password": "another horse"})
            assert r.status_code == 201, r.text
            assert r.json()["current"] == {**r.json()["current"], "tenant": "chase", "member": "dev", "role": "member"}
            assert (await dev.get("/v1/members")).status_code == 200
            assert (await dev.post("/v1/invites", json={"email": "x@example.com"})).status_code == 403   # a member, not an owner
            # a tenant of their own, and switching between the two
            assert (await dev.post("/auth/tenants", json={"name": "devs"})).json()["current"]["tenant"] == "devs"
            assert sorted(t["tenant"] for t in (await dev.get("/auth/me")).json()["tenants"]) == ["chase", "devs"]
            assert (await dev.post("/auth/switch", json={"tenant": "chase"})).json()["current"]["role"] == "member"
            assert (await dev.post("/auth/switch", json={"tenant": "acme"})).status_code == 404
            assert (await dev.post("/auth/logout")).status_code == 200
            assert (await dev.get("/auth/me")).status_code == 401
        assert (await c.get("/v1/invites")).json()["data"] == []            # spent
        # wrong password, then the right one; a changed password
        assert (await c.post("/auth/login", json={"email": "chase@example.com", "password": "wrong"})).status_code == 401
        assert (await c.post("/auth/login", json={"email": "chase@example.com", "password": "correct horse"})).status_code == 200
        assert (await c.post("/auth/password", json={"current": "wrong", "password": "new horse 2"})).status_code == 403
        assert (await c.post("/auth/password", json={"current": "correct horse", "password": "new horse 2"})).status_code == 200
        assert (await c.post("/auth/login", json={"email": "chase@example.com", "password": "new horse 2"})).status_code == 200
        assert (await c.patch("/auth/account", json={"name": "C. Dovey"})).json()["name"] == "C. Dovey"
        # the identity providers are not configured here
        assert (await c.get("/auth/github")).status_code == 404
    run(platform, scenario)


def test_sign_up_is_closed_but_an_invitation_opens_it(tmp_path, vault):
    settings = Settings(data_dir=tmp_path / "data", public_url="http://api.test", signup="closed", deployer_key="hd_deployer")
    app = create_app(Service(settings, vault))

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as c:
            assert (await c.post("/auth/signup", json={"email": "a@example.com", "password": "correct horse"})).status_code == 403
            key = (await c.post("/v1/tenants", json={"name": "acme", "owner": "ops"}, headers=auth("hd_deployer"))).json()["key"]["secret"]
            assert (await c.post("/v1/invites", json={"email": "a@example.com", "role": "owner"}, headers=auth(key))).status_code == 200
            r = await c.post("/auth/signup", json={"email": "a@example.com", "password": "correct horse"})
            assert r.status_code == 201 and r.json()["current"]["tenant"] == "acme" and r.json()["current"]["role"] == "owner"
    asyncio.run(go())


def test_sign_up_with_mail_verifies_first(tmp_path, vault, monkeypatch):
    sent = []
    from harnessgateway.api import accounts as auth_routes
    monkeypatch.setattr(auth_routes.Mail, "send", lambda self, to, subject, text: sent.append((to, subject, text)))
    settings = Settings(data_dir=tmp_path / "data", public_url="http://api.test", signup="open", smtp_url="smtp://mail.test:587", mail_from="hg@test")
    app = create_app(Service(settings, vault))

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api.test") as c:
            r = await c.post("/auth/signup", json={"email": "a@example.com", "password": "correct horse"})
            assert r.status_code == 200 and r.json() == {"verify": True, "email": "a@example.com"} and "hg_session" not in c.cookies
            assert (await c.post("/auth/login", json={"email": "a@example.com", "password": "correct horse"})).status_code == 403
            assert len(sent) == 1 and sent[0][0] == "a@example.com"
            token = sent[0][2].split("token=")[1].split()[0]
            r = await c.get("/auth/verify", params={"token": token})
            assert r.status_code == 303 and r.headers["location"] == "/app" and "hg_session" in c.cookies
            assert (await c.get("/auth/me")).json()["account"]["verified"]
            assert (await c.get("/auth/verify", params={"token": "nope"})).status_code == 400
            # a reset link, then a new password
            assert (await c.post("/auth/reset", json={"email": "a@example.com"})).status_code == 200
            token = sent[-1][2].split("#reset=")[1].split()[0]
            assert (await c.post("/auth/reset/confirm", json={"token": token, "password": "a new horse"})).status_code == 200
            assert (await c.post("/auth/login", json={"email": "a@example.com", "password": "a new horse"})).status_code == 200
    asyncio.run(go())


def test_workspace_files_and_an_rodeo(platform):
    async def scenario(c, node):
        owner = await signup(c)
        key = await ready(c, owner)
        assert (await c.put("/v1/harnesses/cc2", content=archive({"response.sh": RESPONSE_SH}), headers=auth(owner))).status_code == 200
        runs = [await c.post("/v1/responses", json={"model": m, "input": "write out.txt"}, headers=auth(key)) for m in ("cc", "cc2")]
        assert all(r.status_code == 200 and r.json()["status"] == "completed" for r in runs), [r.text for r in runs]
        sid = runs[0].json()["metadata"]["session_id"]
        files = (await c.get(f"/v1/sessions/{sid}/files", headers=auth(key))).json()["data"]
        assert [f["path"] for f in files] == ["README.md", "out.txt"]
        assert (await c.get(f"/v1/sessions/{sid}/files/out.txt", headers=auth(key))).content == b"write out.txt\n"
        assert (await c.get(f"/v1/sessions/{sid}/files/nope.txt", headers=auth(key))).status_code == 404
        assert (await c.get(f"/v1/sessions/{sid}/files/../x", headers=auth(key))).status_code == 404
        entries = [{"response": r.json()["id"]} for r in runs]
        assert (await c.post("/v1/rodeos", json={"prompt": "p", "entries": entries[:1]}, headers=auth(key))).status_code == 400
        a = (await c.post("/v1/rodeos", json={"prompt": "write out.txt", "entries": entries}, headers=auth(key))).json()
        assert [e["harness"] for e in a["entries"]] == ["cc", "cc2"] and a["winner"] == ""
        assert (await c.patch(f"/v1/rodeos/{a['id']}", json={"winner": "zz"}, headers=auth(key))).status_code == 400
        assert (await c.patch(f"/v1/rodeos/{a['id']}", json={"winner": "cc2"}, headers=auth(key))).json()["winner"] == "cc2"
        board = (await c.get("/v1/rodeos", headers=auth(key))).json()
        assert len(board["data"]) == 1 and board["leaderboard"] == [{"harness": "cc2", "runs": 1, "wins": 1}, {"harness": "cc", "runs": 1, "wins": 0}]
        assert (await c.get(f"/v1/rodeos/{a['id']}", headers=auth(owner))).status_code == 200    # the owner sees the member's
        other = await signup(c, "other", "o")
        assert (await c.get(f"/v1/rodeos/{a['id']}", headers=auth(other))).status_code == 404
        assert (await c.delete(f"/v1/rodeos/{a['id']}", headers=auth(key))).status_code == 200
        assert (await c.get("/v1/rodeos", headers=auth(key))).json()["data"] == []
        assert (await c.get("/v1/arenas", headers=auth(key))).json()["data"] == []            # the 6.0 path still answers
    run(platform, scenario)
