"""Layer 5: sessions, with the template's stand-in on this machine. A request makes a session and its
response runs in the background, owned by the service; continuing it stays on its harness and
provider and resumes the CLI's conversation; one response runs at a time; following a session sees
every event from the first until it is idle, across continuations; interrupt degrades exactly as the
contract says; stop is graceful, a kill when it can't wait, and nothing when idle; steers the harness
didn't take are sent again when it ends `ok`; every artifact is there while it runs and after; a
restart closes what was in flight; and the provider's key is in no record, log or artifact."""
import asyncio
import json
import os
import time

import pytest

from harness_interface import Ask, Invalid, NotFound, Conflict, Placement, Sessions
from harness_interface.runtimes.docker import owner_of
from harness_interface.sessions import ResponseRecord, Session
from harness_interface.store import ProviderEntry
from standin import TEMPLATE, events
from test_store import template_map
from upstream import Upstream

KEY = "sk-sessions-test-key-" + os.urandom(6).hex()


class World:
    """A data directory with the template registered, its provider a stand-in reached through the gateway."""

    def __init__(self, tmp_path):
        self.tmp, self.data = tmp_path, tmp_path / "data"
        self.up = Upstream(tmp_path)
        self.url = self.up.url + "/anthropic"

    def sessions(self) -> Sessions:
        return Sessions(self.data, Placement(ca_file=self.up.ca))

    async def ready(self, change=None, name="template", **files) -> Sessions:
        """Sessions with the template (changed by `change`, as `name`) and the provider `up` registered."""
        s = self.sessions()
        s.registry.put_provider(ProviderEntry("up", self.url, "anthropic-messages", KEY))

        def spec(sp):
            sp["provider"]["url"] = self.url
            sp["name"] = name
            if change:
                change(sp)
        await s.registry.put_harness(name, template_map(spec, **files))
        await s.registry.ready(name)
        return s


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.up.close()


def run(coro_fn):
    """Run a test's coroutine, closing every Sessions it made, whatever happens."""
    async def go():
        made = []
        try:
            return await coro_fn(made)
        finally:
            for s in made:
                await s.close()
    return asyncio.run(go())


class Seen:
    """What a follower saw: every event, and the stand-in's NDJSON events per response."""

    def __init__(self):
        self.all, self.out = [], {}

    def add(self, event):
        self.all.append(event)
        if event.kind == "stdout":
            self.out[event.response] = self.out.get(event.response, b"") + event.data

    def ndjson(self, rid):
        return events(self.out.get(rid, b""))

    def count(self, rid):
        return max([e["n"] for e in self.ndjson(rid) if e.get("type") == "count"], default=0)

    def kinds(self):
        return [(e.kind, e.response) for e in self.all if e.kind != "stdout" and e.kind != "stderr"]


async def follow(sessions, ident, on=None) -> Seen:
    seen = Seen()
    async for event in sessions.follow(ident):
        seen.add(event)
        if on and event.kind == "stdout":
            await on(seen, event.response)
    return seen


# a session and its responses
def test_a_request_makes_a_session_and_its_response_runs_in_the_background(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 2", instructions="Be brief."))
        rid = s.responses[-1]
        active = sessions.session(s.id).status
        record = await sessions.wait(rid)
        return sessions, s, active, record
    sessions, s, active, record = run(go)
    assert s.id.startswith("sess_") and record.id.startswith("resp_") and active == "active"
    assert (record.status, record.answer, record.session, record.harness, record.provider) == \
        ("completed", "Counted to 2.", s.id, "template", "up")
    assert record.usage == {"input_tokens": 3, "output_tokens": 2} and record.resume and record.base and record.commit
    after = sessions.session(s.id)
    assert (after.status, after.resume, after.responses, after.interrupt) == ("idle", record.resume, [record.id], "steered")
    assert [x.id for x in sessions.sessions()] == [s.id] and sessions.response(record.id).status == "completed"
    loaded = next(e for e in events(sessions.artifacts(record.id).stdout) if e["type"] == "loaded")
    assert loaded["instructions"] == "Be brief."


def test_continuing_a_response_resumes_its_session_and_stays_on_its_harness_and_provider(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        await sessions.registry.put_harness("other", template_map(
            lambda sp: sp.update(name="other", provider={"url": world.url, "api": "anthropic-messages"})))
        sessions.registry.put_provider(ProviderEntry("up2", world.url, "anthropic-messages", KEY))
        first = await sessions.wait((await sessions.start(Ask("template", "count to 2"))).responses[-1])
        s = await sessions.start(Ask("template/standin-2", "count to 3", previous=first.id))
        second = await sessions.wait(s.responses[-1])
        for model in ("other", "template@up2"):
            with pytest.raises(Invalid, match="stays on"):
                await sessions.start(Ask(model, "x", previous=second.id))
        with pytest.raises(NotFound):
            await sessions.start(Ask("template", "x", previous="resp_0000000000000000"))
        return sessions, first, second
    sessions, first, second = run(go)
    assert second.session == first.session and second.previous == first.id and second.model == "template/standin-2"
    started = next(e for e in events(sessions.artifacts(second.id).stdout) if e["type"] == "session")
    assert started["resumed"] and started["count"] == 2 and started["model"] == "standin-2"
    assert second.answer == "Counted to 3." and sessions.session(first.session).responses == [first.id, second.id]


def test_a_session_runs_one_response_at_a_time(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 3"))
        with pytest.raises(Conflict):
            await sessions.start(Ask("template", "count to 1", previous=s.responses[-1]))
        await sessions.wait(s.responses[-1])
        again = await sessions.start(Ask("template", "count to 4", previous=s.responses[-1]))
        return await sessions.wait(again.responses[-1])
    assert run(go).status == "completed"


def test_the_model_names_a_harness_and_maybe_a_provider_and_a_model(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        named = await sessions.wait((await sessions.start(Ask("template@up/standin-9", "count to 1"))).responses[-1])
        refused = []
        for model in ("nope", "template@nope", "", "@up", "template@"):
            with pytest.raises((Invalid, NotFound)) as e:
                await sessions.start(Ask(model, "count to 1"))
            refused.append(e.type)
        sessions.registry.put_provider(ProviderEntry("chat", "https://api.openai.com/v1", "openai-chat", KEY))
        one = await world.ready(lambda sp: sp.update(apis=["anthropic-messages"]), name="one")
        made.append(one)
        with pytest.raises(Invalid, match="openai-chat"):
            await one.start(Ask("one@chat", "count to 1"))
        lonely = await world.ready(lambda sp: sp["provider"].update(url="https://api.anthropic.com"), name="lonely")
        made.append(lonely)
        with pytest.raises(Invalid, match="no provider"):
            await lonely.start(Ask("lonely", "count to 1"))
        return sessions, named, refused
    sessions, named, refused = run(go)
    assert set(refused) == {Invalid}
    assert named.provider == "up" and named.model == "template@up/standin-9"
    assert next(e for e in events(sessions.artifacts(named.id).stdout) if e["type"] == "session")["model"] == "standin-9"
    assert len(sessions.sessions()) == 1                                 # nothing refused left a session behind


def test_a_session_keeps_one_provider_url_and_key_path_for_its_life(world):
    note = 'echo "$HI_PROVIDER_URL $HI_PROVIDER_KEY_FILE" >> "$HOME/provider"\n'
    run_sh = (TEMPLATE / "run.sh").read_text().replace('exec python3', note + 'exec python3')

    async def go(made):
        sessions = await world.ready(**{"run.sh": run_sh})
        made.append(sessions)
        first = await sessions.wait((await sessions.start(Ask("template", "count to 1"))).responses[-1])
        await sessions.wait((await sessions.start(Ask("template", "count to 2", previous=first.id))).responses[-1])
        return sessions.session(first.session)
    s = run(go)
    seen = (world.data / "workspaces" / s.id / ".home" / "provider").read_text().splitlines()
    assert len(seen) == 2 and seen[0] == seen[1] and seen[0].startswith("http://127.0.0.1:")


# following
def test_following_sees_every_event_from_the_first_and_ends_when_idle(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 3"))
        rid = s.responses[-1]
        while b'"n": 1' not in sessions.artifacts(rid).stdout:          # a follower that comes late
            await asyncio.sleep(0.05)
        live = await follow(sessions, s.id)
        replay = await follow(sessions, rid)                            # a finished response, replayed
        idle = await follow(sessions, s.id)
        with pytest.raises(NotFound):
            sessions.follow("sess_0000000000000000")
        return rid, live, replay, idle
    rid, live, replay, idle = run(go)
    assert live.kinds() == [("created", rid), ("completed", rid)] and live.count(rid) == 3
    assert live.all[0].record.status == "in_progress" and live.all[-1].record.status == "completed"
    assert replay.kinds() == live.kinds() and replay.out == live.out
    assert idle.all == []


def test_a_response_outlives_whoever_was_following_it(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 3"))
        async for event in sessions.follow(s.id):
            if event.kind == "stdout":
                break                                                    # the client left
        return await sessions.wait(s.responses[-1])
    record = run(go)
    assert record.status == "completed" and record.answer == "Counted to 3."


# interrupt
def test_interrupting_an_idle_session_continues_it(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 1"))
        first = await sessions.wait(s.responses[-1])
        outcome, record = await sessions.interrupt(s.id, "count to 2")
        return sessions, first, outcome, await sessions.wait(record.id)
    sessions, first, outcome, second = run(go)
    assert outcome == "continued" and second.previous == first.id and second.answer == "Counted to 2."
    log = sessions.session(first.session).interrupts
    assert [(i["input"], i["outcome"], i["response"]) for i in log] == [("count to 2", "continued", second.id)]


def test_interrupting_a_steered_response_steers_it(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 30"))
        got = []

        async def on(seen, rid):
            if seen.count(rid) == 2 and not got:
                got.append(await sessions.interrupt(s.id, "now count to 4"))
        seen = await follow(sessions, s.id, on)
        return sessions, s, got[0], seen
    sessions, s, (outcome, record), seen = run(go)
    final = sessions.response(record.id)
    assert outcome == "steered" and record.id == s.responses[-1]
    kinds = [e.kind for e in seen.all]
    assert kinds.index("steer") > kinds.index("stdout") and kinds[-1] == "completed"
    assert next(e for e in seen.all if e.kind == "steer").data == b"now count to 4"
    assert (final.status, final.answer, [x["input"] for x in final.steers], final.undelivered) == \
        ("completed", "Counted to 4.", ["now count to 4"], [])
    assert sessions.session(s.id).interrupts[0]["outcome"] == "steered"


@pytest.mark.parametrize("tier", ["continued", "responded"])
def test_interrupting_a_response_that_takes_no_steers_stops_it_and_continues_with_the_text(world, tier):
    async def go(made):
        sessions = await world.ready(lambda sp: sp["run"].update(interrupt=tier))
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 30"))
        got = []

        async def on(seen, rid):
            if seen.count(rid) == 2 and not got:
                got.append(await sessions.interrupt(s.id, "count to 5"))
        seen = await follow(sessions, s.id, on)
        return sessions, s, got[0], seen
    sessions, s, (outcome, second), seen = run(go)
    first = sessions.response(s.responses[0])
    assert outcome == tier and second.previous == first.id
    assert (first.status, first.stop) == ("cancelled", "stopped")
    assert seen.kinds() == [("created", first.id), ("completed", first.id), ("interrupted", second.id),
                            ("created", second.id), ("completed", second.id)]
    interrupted = next(e for e in seen.all if e.kind == "interrupted")
    assert (interrupted.outcome, interrupted.source, interrupted.data) == (tier, first.id, b"count to 5")
    resumed = next(e for e in seen.ndjson(second.id) if e["type"] == "session")
    assert resumed["resumed"] and resumed["count"] == 2
    assert sessions.response(second.id).answer == "Counted to 5."


def test_a_steer_that_cant_be_delivered_falls_through_to_stop_and_continue(world, monkeypatch):
    from harness_interface.harness.response import Response

    async def undeliverable(self, text):
        raise Invalid("its input is closed")
    monkeypatch.setattr(Response, "steer", undeliverable)

    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 30"))
        got = []

        async def on(seen, rid):
            if seen.count(rid) == 1 and not got:
                got.append(await sessions.interrupt(s.id, "count to 3"))
        await follow(sessions, s.id, on)
        return got[0]
    outcome, record = run(go)
    assert outcome == "continued" and record.previous


# stop
def test_stopping_is_graceful_a_kill_when_it_cant_wait_and_nothing_when_idle(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        results = []
        for timeout in (None, 0):
            s = await sessions.start(Ask("template", "count to 30"))
            got = []

            async def on(seen, rid):
                if seen.count(rid) == 2 and not got:
                    got.append(await sessions.stop(s.id, timeout))
            await follow(sessions, s.id, on)
            results.append((got[0], sessions.response(s.responses[-1]), sessions.session(s.id)))
        idle = await sessions.stop(s.id)
        with pytest.raises(NotFound):
            await sessions.stop("sess_0000000000000000")
        return results, idle
    ((graceful, r1, s1), (killed, r2, s2)), idle = run(go)
    assert graceful == "stopped" and (r1.status, r1.stop, r1.exit_code) == ("cancelled", "stopped", 0) and r1.resume
    assert killed == "killed" and (r2.status, r2.stop) == ("cancelled", "killed") and r2.resume
    assert idle == "idle" and s1.status == s2.status == "idle"
    assert [i["outcome"] for i in s1.interrupts] == ["stopped"] and s2.interrupts[0]["outcome"] == "killed"


def test_a_stop_before_the_harness_has_started_stops_it_from_starting(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 30"))
        outcome = await sessions.stop(s.id)                             # still being prepared
        return outcome, sessions.response(s.responses[-1])
    outcome, record = run(go)
    assert outcome == "stopped" and (record.status, record.stop) == ("cancelled", "stopped")


# steers the harness didn't take
DEAF = (TEMPLATE / "adapter.py").read_text().replace(
    '''        self.queued += 1
        self.send({"type": "steer", "text": text})''', '''        pass                                         # a CLI that finishes without taking a late steer''')


def test_steers_the_harness_didnt_take_are_sent_again_when_it_ends_ok(world):
    assert DEAF != (TEMPLATE / "adapter.py").read_text()

    async def go(made):
        sessions = await world.ready(**{"adapter.py": DEAF})
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 3"))
        got = []

        async def on(seen, rid):
            if seen.count(rid) == 1 and not got:
                got.append(await sessions.interrupt(s.id, "count to 5"))
        seen = await follow(sessions, s.id, on)
        return sessions, sessions.session(s.id), seen
    sessions, s, seen = run(go)
    first, second = (sessions.response(r) for r in s.responses)
    assert (first.status, first.answer, first.undelivered) == ("completed", "Counted to 3.", ["count to 5"])
    assert second.previous == first.id and second.request["input"] == "count to 5"
    assert (second.status, second.answer) == ("completed", "Counted to 5.")
    assert seen.kinds() == [("created", first.id), ("steer", first.id), ("completed", first.id),
                            ("interrupted", second.id), ("created", second.id), ("completed", second.id)]


def test_steers_not_taken_by_a_stopped_response_are_reported_undelivered(world):
    async def go(made):
        sessions = await world.ready(**{"adapter.py": DEAF})
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 30"))
        done = []

        async def on(seen, rid):
            if seen.count(rid) == 1 and not done:
                done.append(await sessions.interrupt(s.id, "count to 5"))
            elif seen.count(rid) == 3 and len(done) == 1:
                done.append(await sessions.stop(s.id))
        await follow(sessions, s.id, on)
        return sessions.session(s.id), sessions.response(s.responses[-1])
    s, record = run(go)
    assert len(s.responses) == 1 and record.status == "cancelled" and record.undelivered == ["count to 5"]


# artifacts
def test_every_artifact_is_there_while_it_runs_and_after(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        files = {"data/in.txt": "seed\n", "data/blob.bin": b"\x00\xff"}
        s = await sessions.start(Ask("template", "count to 4", files=files))
        rid, live = s.responses[-1], []

        async def on(seen, r):
            if seen.count(r) == 2 and not live:
                live.append(sessions.artifacts(r))
        await follow(sessions, s.id, on)
        return sessions.response(rid), live[0], sessions.artifacts(rid)
    record, live, done = run(go)
    assert b'"type": "count"' in live.stdout and live.output["status"] == "running" and live.output["resume"]
    assert "+1" in live.diff and live.changes["count.txt"].startswith(b"1\n2\n")
    assert {"count.txt", "data/in.txt", "data/blob.bin"} <= set(live.files)
    assert done.changes == {"count.txt": b"1\n2\n3\n4\n"}                 # the request's files came before it
    assert {"data/in.txt", "data/blob.bin"} <= set(done.files)
    assert "+4" in done.diff and done.output["status"] == "ok" and done.output["count"] == 4
    memory = f".standin/memory/{record.resume}.md"
    assert done.home == {memory: b"- count to 4\n"} and live.home == {memory: b"- count to 4\n"}
    assert not any(p.startswith(".home") for p in done.files)


# recovery
def test_with_no_placement_a_session_service_owns_the_runs_of_its_data_directory(tmp_path):
    assert Sessions(tmp_path / "data").placement.owner == owner_of(tmp_path / "data")


def test_a_restart_closes_what_was_in_flight_and_keeps_its_resume(world):
    sessions = world.sessions()
    ws = world.data / "workspaces" / "sess_00000000000000aa"
    sessions.store.put("sess_00000000000000aa", Session(
        id="sess_00000000000000aa", harness="template", provider="up", model="template", interrupt="steered",
        workspace=str(ws), token="sk-hi-token", status="active", responses=["resp_00000000000000aa"]))
    sessions.records.put("resp_00000000000000aa", ResponseRecord(
        id="resp_00000000000000aa", session="sess_00000000000000aa", model="template", harness="template",
        provider="up", request={"input": "count to 9"}))
    rundir = world.data / "runs" / "resp_00000000000000aa"
    rundir.mkdir(parents=True)
    (rundir / "output.json").write_text(json.dumps({"status": "running", "resume": "cli-session-1"}))

    async def go():
        again = world.sessions()
        await again.recover()
        return again
    again = asyncio.run(go())
    record, s = again.response("resp_00000000000000aa"), again.session("sess_00000000000000aa")
    assert (record.status, record.error["code"], record.resume) == ("failed", "server_restarted", "cli-session-1")
    assert (s.status, s.resume) == ("idle", "cli-session-1")


# secrets
def test_the_providers_key_is_in_no_record_log_or_artifact(world):
    async def go(made):
        sessions = await world.ready()
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 2"))
        record = await sessions.wait(s.responses[-1])
        return sessions, record
    sessions, record = run(go)
    assert {"type": "provider", "status": 200} in events(sessions.artifacts(record.id).stdout)
    assert f"x-api-key: {KEY}" in world.up.requests[0].decode("latin-1")
    for p in world.data.rglob("*"):
        if p.is_file() and "providers" not in p.parts:
            assert KEY.encode() not in p.read_bytes(), p
    a = sessions.artifacts(record.id)
    assert KEY not in repr(a) and KEY not in json.dumps(record.__dict__) and KEY not in repr(sessions.session(record.session))


def test_the_library_drives_a_session_with_no_server(world):
    """The plan's own example, as written."""
    async def go(made):
        await (await world.ready()).close()
        sessions = Sessions(world.data, Placement(ca_file=world.up.ca))
        made.append(sessions)
        s = await sessions.start(Ask("template", "count to 30"))
        began = time.monotonic()
        async for event in sessions.follow(s.id):
            if event.kind == "stdout" and b'"n": 2' in event.data:
                await sessions.interrupt(s.id, "Stop; count to 3 instead")
                await sessions.stop(s.id)
        return sessions.session(s.id), time.monotonic() - began
    s, took = run(go)
    assert s.status == "idle" and took < 20
