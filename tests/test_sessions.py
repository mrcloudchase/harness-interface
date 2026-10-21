"""Layer 5: a turn runs request.sh with the prompt on stdin and comes back as its two streams and
exit code; seeds land where they should; a session continues; store:false keeps no workspace;
cancel, timeout, busy; who reaches what."""
import asyncio

import pytest

from fakes import FakeRuntimes, archive
from harness_interface.errors import Conflict, Invalid, NotFound
from harness_interface.sessions import Ask, Sessions


@pytest.fixture
def sessions(store):
    store.create_org("acme", max_runs=2)
    store.create_member("acme", "chase", "owner")
    store.create_member("acme", "dev", "member")
    store.put_provider("acme", "prov", "https://api.example", "openai-chat", "sk-real-secret")
    store.put_sandbox("acme", "box", image="img")
    store.put_harness("acme", "cc", archive())
    return Sessions(store, FakeRuntimes())


def ask(prompt="hello", member="dev", **kw):
    return Ask("acme", member, "cc", prompt, body={"input": prompt}, **kw)


async def run(sessions, a):
    r = await sessions.create(a)
    return await sessions.wait(r.id)


def test_a_turn(sessions, store):
    r = asyncio.run(run(sessions, ask(instructions="be brief")))
    assert r.status == "completed" and r.exit_code == 0 and r.error == ""
    assert r.stderr == "stderr line\n"
    assert "prompt=hello turn=1 model=m1 key=sk-hi-" in r.stdout and "url=http://hi-provider:8080" in r.stdout
    assert "ins=be brief" in r.stdout and "sk-real-secret" not in r.stdout
    assert "org=from-org" in r.stdout and "user=from-user" in r.stdout and "project=from-project" in r.stdout
    assert (r.sandbox, r.provider, r.model, r.turn, r.store) == ("box", "prov", "m1", 1, True)
    chase, dev = store.member("acme", "chase"), store.member("acme", "dev")
    s = sessions.session(dev, r.session)
    assert s.responses == [r.id] and s.stored and sessions.sessions(dev) == [s] and sessions.sessions(chase) == [s]
    assert (sessions._dir(s) / "workspace" / "out.txt").read_text() == "hello\n"
    trace = sessions.trace(dev, s.id)
    assert [t["kind"] for t in trace] == ["request", "response"] and trace[0]["body"] == {"input": "hello"}
    assert trace[1]["body"]["stdout"] == r.stdout
    assert sessions.runtimes.installs == 1


def test_continue_and_overrides(sessions, store):
    store.put_sandbox("acme", "gpu", image="img2")
    store.put_provider("acme", "other", "https://o.example", "openai-chat", "k")
    r1 = asyncio.run(run(sessions, ask()))
    r2 = asyncio.run(run(sessions, ask("again", previous=r1.id, sandbox="gpu", provider="other", model="m2")))
    assert r2.session == r1.session and r2.turn == 2 and "turn=2 model=m2" in r2.stdout
    assert (r2.sandbox, r2.provider) == ("gpu", "other") and sessions.runtimes.installs == 2
    dev = store.member("acme", "dev")
    assert sessions.session(dev, r1.session).responses == [r1.id, r2.id]
    assert sessions.records(dev, r1.session)[1].id == r2.id
    with pytest.raises(NotFound):
        asyncio.run(run(sessions, ask(previous="resp_nope")))


def test_stateless_keeps_no_workspace(sessions, store):
    r = asyncio.run(run(sessions, ask(store=False)))
    dev = store.member("acme", "dev")
    s = sessions.session(dev, r.session)
    assert r.status == "completed" and not s.stored and not (sessions._dir(s) / "workspace").exists()
    assert sessions.trace(dev, s.id)[1]["body"]["stdout"] == r.stdout
    with pytest.raises(Invalid, match="not stored"):
        asyncio.run(run(sessions, ask(previous=r.id)))
    with pytest.raises(NotFound):
        asyncio.run(sessions.archive(dev, s.id))


def test_files_and_seeds_rules(sessions, store):
    r = asyncio.run(run(sessions, ask(files={"notes/a.txt": b"A", "README.md": b"mine"})))
    assert "project=mine" in r.stdout                 # a request's file wins over the project seed
    s = sessions.session(store.member("acme", "dev"), r.session)
    assert (sessions._dir(s) / "workspace" / "notes" / "a.txt").read_bytes() == b"A"
    home = sessions._home("acme", "dev", "cc")
    (home / "user.txt").write_text("edited")
    (home / "org.txt").write_text("edited")
    r2 = asyncio.run(run(sessions, ask(previous=r.id)))
    assert "user=edited" in r2.stdout and "org=from-org" in r2.stdout   # user's stays, org's is reapplied
    with pytest.raises(Invalid):
        Ask("acme", "dev", "cc", "x", files={"../escape": b""})


def test_defaults_are_required(sessions, store):
    store.put_harness("acme", "bare", archive(defaults="{}"))
    with pytest.raises(Invalid, match="no sandbox"):
        asyncio.run(run(sessions, Ask("acme", "dev", "bare", "x")))
    with pytest.raises(Invalid, match="no provider"):
        asyncio.run(run(sessions, Ask("acme", "dev", "bare", "x", sandbox="box")))
    with pytest.raises(NotFound):
        asyncio.run(run(sessions, Ask("acme", "dev", "bare", "x", sandbox="nope", provider="prov")))


def test_failure_timeout_and_setup_errors(sessions, store):
    store.put_harness("acme", "bad", archive({"request.sh": "#!/bin/bash\necho oops >&2\nexit 3\n"}))
    r = asyncio.run(run(sessions, Ask("acme", "dev", "bad", "x")))
    assert r.status == "failed" and r.exit_code == 3 and r.error == "request.sh exited 3" and r.stderr == "oops\n"
    store.put_harness("acme", "slow", archive({"request.sh": "#!/bin/bash\nsleep 30\n"}, run='{"timeout_s": 0.5}'))
    r = asyncio.run(run(sessions, Ask("acme", "dev", "slow", "x")))
    assert r.status == "incomplete" and "ran past" in r.error
    store.put_harness("acme", "noinstall", archive({"install.sh": "#!/bin/bash\nexit 1\n"}))
    r = asyncio.run(run(sessions, Ask("acme", "dev", "noinstall", "x")))
    assert r.status == "failed" and r.exit_code is None and r.error


def test_cancel_busy_and_interrupt(sessions, store):
    store.put_harness("acme", "slow", archive({"request.sh": "#!/bin/bash\necho started\nsleep 30\n"}))
    dev = store.member("acme", "dev")

    async def go():
        r = await sessions.create(Ask("acme", "dev", "slow", "x"))
        with pytest.raises(Conflict):
            await sessions.create(Ask("acme", "dev", "slow", "y", previous=r.id))
        with pytest.raises(Conflict, match="not running"):      # no container to signal without Docker
            await sessions.interrupt(dev, r.session, "turn left")
        await asyncio.sleep(0.3)
        return await sessions.cancel(dev, r.id)
    r = asyncio.run(go())
    assert r.status == "cancelled" and r.stdout == "started\n"
    with pytest.raises(Conflict, match="not running"):
        asyncio.run(sessions.interrupt(dev, r.session, "x"))


def test_follow_and_archive(sessions, store):
    dev = store.member("acme", "dev")

    async def go():
        r = await sessions.create(ask())
        seen = [e async for e in sessions.follow(dev, r.id)]
        final = await sessions.wait(r.id)
        replay = [e async for e in sessions.follow(dev, r.id)]
        return seen, final, replay
    seen, final, replay = asyncio.run(go())
    assert "".join(t for s, t in seen if s == "stdout") == final.stdout and ("stderr", "stderr line\n") in seen
    assert replay == [("stdout", final.stdout), ("stderr", final.stderr)]
    data = asyncio.run(sessions.archive(dev, final.session))
    import io, tarfile
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert "./out.txt" in tar.getnames()


def test_reach_and_delete(sessions, store):
    r = asyncio.run(run(sessions, ask()))
    chase, dev = store.member("acme", "chase"), store.member("acme", "dev")
    store.create_org("other")
    store.create_member("other", "eve", "owner")
    eve = store.member("other", "eve")
    store.create_member("acme", "peer", "member")
    peer = store.member("acme", "peer")
    for who in (eve, peer):
        with pytest.raises(NotFound):
            sessions.session(who, r.session)
        with pytest.raises(NotFound):
            sessions.response(who, r.id)
        assert sessions.sessions(who) == []
    assert sessions.response(chase, r.id).id == r.id           # an owner reaches every member's
    asyncio.run(sessions.delete(dev, r.session))
    with pytest.raises(NotFound):
        sessions.response(dev, r.id)
    assert sessions.sessions(chase) == []


def test_recover_closes_what_a_restart_cut_off(sessions, store):
    r = asyncio.run(run(sessions, ask()))
    s, rec = sessions._record_by_id(r.id)
    rec.status = "in_progress"
    sessions._save_record(s, rec)
    sessions.runtimes.owner = "0" * 12
    import harness_interface.sessions as mod
    async def no_sweep(owner):
        pass
    mod.sweep = no_sweep
    asyncio.run(sessions.recover())
    assert sessions._record_by_id(r.id)[1].status == "failed"
