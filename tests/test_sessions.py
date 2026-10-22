"""Layer 5, the control plane's side: a turn is queued, claimed by a worker with its job, streamed,
ended; a session continues from its snapshot; reach rules; cancel and steer as commands; a lost
worker fails its turn and frees the session; store:false keeps no snapshot."""
import io
import tarfile
import time

import pytest

from fakes import archive
from harness_interface.blobs import DirBlobs
from harness_interface.errors import Conflict, Invalid, NotFound
from harness_interface.records import SqliteRecords
from harness_interface.sessions import Ask, Sessions
from harness_interface.store import Store


@pytest.fixture
def sessions(tmp_path, vault):
    store = Store(SqliteRecords(tmp_path / "r.db"), DirBlobs(tmp_path / "b", "http://api.test", b"s"), vault)
    store.create_tenant("acme", {"max_runs": 1})
    store.create_member("acme", "chase", "owner")
    store.create_member("acme", "dev", "member")
    store.put_provider("acme", "prov", "https://api.example/v1", "openai-chat", "sk-real-secret")
    store.put_harness("acme", "cc", archive())
    return Sessions(store, "http://api.test", "http://gateway.test:8081")


def ask(prompt="hello", member="dev", **kw):
    return Ask("acme", member, "cc", prompt, body={"input": prompt}, **kw)


def worker(sessions, name="w1"):
    w, _ = sessions.store.register_worker(name, 4, "t")
    return w


def finish(sessions, w, rid, **body):
    return sessions.result(w, rid, {"outcome": "exited", "exit_code": 0, "output": "shaped", "stdout": "raw\n",
                                    "stderr": "", "seconds": 1.5, "snapshot": True, **body})


def test_queue_claim_run_end(sessions):
    store = sessions.store
    r = sessions.create(ask(instructions="be brief", files={"notes/a.txt": b"A"}))
    assert r.status == "queued" and r.turn == 1 and r.files.endswith("files.tgz")
    w = worker(sessions)
    job = sessions.claim(w)
    assert job and job["id"] == r.id and job["token"].startswith("sk-hi-") and job["provider"]["url"] == "http://hi-provider:8080/v1"
    assert job["urls"]["folder"].startswith("http://api.test/internal/blobs/") and job["urls"]["workspace"] == "" and job["urls"]["files"]
    assert job["config"]["run"]["egress"] == ["git.example"] and job["limits"]["max_runs"] == 1 and job["timeout_s"] == 60
    assert job["request"] == {"input": "hello"} and job["instructions"] == "be brief" and job["new_session"]
    assert store.resolve_token(job["token"])["response"] == r.id
    assert sessions.claim(w) is None                      # max_runs 1: nothing else while this runs
    sessions.started(w, r.id)
    sessions.chunks_in(w, r.id, [{"seq": 1, "stream": "stdout", "text": "ra"}, {"seq": 2, "stream": "stdout", "text": "w\n"}])
    assert sessions.commands(w, [r.id]) == {r.id: {"cancel": False, "interrupts": []}}
    done = finish(sessions, w, r.id)
    dev = store.member("acme", "dev")
    assert done.status == "completed" and done.output == "shaped" and done.stdout == "raw\n" and done.running == "0"
    s = sessions.session(dev, r.session)
    assert s.responses == [r.id] and not s.running and s.workspace.endswith("workspace.tgz") and s.snapshot == r.id
    assert [t["kind"] for t in sessions.trace(dev, s.id)] == ["request", "response"]
    assert store.records.get("usage", "acme", r.id)["seconds"] == 1.5
    with pytest.raises(Conflict):
        finish(sessions, worker(sessions, "other"), r.id)   # another worker cannot end it


def test_continue_overrides_and_reach(sessions):
    store = sessions.store
    store.put_provider("acme", "other", "https://o.example", "anthropic-messages", "k")
    w = worker(sessions)
    r1 = sessions.create(ask())
    sessions.claim(w)
    sessions.blobs.put(f"tenants/acme/sessions/{r1.session}/workspace.tgz", b"snap")
    finish(sessions, w, r1.id)
    r2 = sessions.create(ask("again", previous=r1.id, provider="other", model="m2"))
    assert r2.session == r1.session and r2.turn == 2 and (r2.provider, r2.model) == ("other", "m2")
    job = sessions.claim(w)
    assert job["urls"]["workspace"] and job["snapshot"] == r1.id and not job["new_session"] and job["token"].startswith("sk-ant-api03-hi-")
    with pytest.raises(Conflict):
        sessions.create(ask("busy", previous=r1.id))
    finish(sessions, w, r2.id)
    chase, dev = store.member("acme", "chase"), store.member("acme", "dev")
    assert [x.id for x in sessions.records_of(dev, r1.session)] == [r1.id, r2.id]
    store.create_tenant("other")
    store.create_member("other", "eve", "owner")
    store.create_member("acme", "peer", "member")
    for who in (store.member("other", "eve"), store.member("acme", "peer")):
        with pytest.raises(NotFound):
            sessions.session(who, r1.session)
        with pytest.raises(NotFound):
            sessions.response(who, r1.id)
        assert sessions.sessions(who) == []
    assert sessions.response(chase, r1.id).id == r1.id
    with pytest.raises(NotFound):
        sessions.create(ask(previous="resp_nope"))
    store.put_harness("acme", "other", archive())
    with pytest.raises(Invalid, match="runs cc, not other"):
        sessions.create(Ask("acme", "dev", "other", "x", previous=r1.id))


def test_cancel_interrupt_and_lost_worker(sessions):
    store = sessions.store
    dev = store.member("acme", "dev")
    r = sessions.create(ask())
    assert sessions.cancel(dev, r.id).status == "cancelled"         # queued: ends at once
    assert not sessions.session(dev, r.session).running
    r = sessions.create(ask("wait"))
    with pytest.raises(Conflict, match="not running"):
        sessions.interrupt(dev, r.session, "turn")                     # queued: nothing to steer yet
    w = worker(sessions)
    sessions.claim(w)
    sessions.started(w, r.id)
    sessions.interrupt(dev, r.session, "turn left")
    sessions.cancel(dev, r.id)
    assert sessions.commands(w, [r.id])[r.id] == {"cancel": True, "interrupts": [{"seq": 1, "text": "turn left"}]}
    finish(sessions, w, r.id, outcome="stopped", exit_code=0)
    assert sessions.response(dev, r.id).status == "cancelled"
    assert [t["kind"] for t in sessions.trace(dev, r.session)] == ["request", "interrupt", "cancel", "response"]
    r = sessions.create(ask("lost"))
    sessions.claim(w)
    store.records.put("worker", "", w.id, {**store.records.get("worker", "", w.id), "last_seen": time.time() - 999})
    assert sessions.sweep_lost() == [r.id]
    got = sessions.response(dev, r.id)
    assert got.status == "failed" and "lost" in got.error and not sessions.session(dev, r.session).running


def test_stateless_archive_delete(sessions):
    store = sessions.store
    dev = store.member("acme", "dev")
    w = worker(sessions)
    r = sessions.create(ask(store=False))
    job = sessions.claim(w)
    assert job["urls"]["workspace_put"] == "" and not job["store"]
    finish(sessions, w, r.id, snapshot=False)
    s = sessions.session(dev, r.session)
    assert not s.stored and not s.workspace
    with pytest.raises(Invalid, match="not stored"):
        sessions.create(ask(previous=r.id))
    with pytest.raises(NotFound):
        sessions.archive(dev, s.id)
    r = sessions.create(ask())
    sessions.claim(w)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("out.txt")
        info.size = 5
        tar.addfile(info, io.BytesIO(b"hello"))
    sessions.blobs.put(f"tenants/acme/sessions/{r.session}/workspace.tgz", buf.getvalue())
    finish(sessions, w, r.id)
    with tarfile.open(fileobj=io.BytesIO(sessions.archive(dev, r.session))) as tar:
        assert "out.txt" in tar.getnames()
    sessions.delete(dev, r.session)
    with pytest.raises(NotFound):
        sessions.response(dev, r.id)
    assert sessions.blobs.list(f"tenants/acme/sessions/{r.session}") == []
