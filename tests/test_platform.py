"""Layer 6: turns run in the background and outlive whoever follows them; a conversation continues
in its workspace and session, one turn at a time; cancel works at any point; a restart closes
whatever was in flight. No HTTP anywhere."""
import asyncio
import time
from pathlib import Path

import pytest

from harness_interface.errors import Conflict, Invalid, NotFound
from harness_interface.execution import NeverStarted
from harness_interface.harness import Harness, Provider
from harness_interface.platform import Ask, LocalPlacement, Record, Service
from harness_interface.resources import Registry

ECHO = Path(__file__).parent / "echo"
SLOW = 'echo start; sleep {s}; echo end; printf \'{{"status":"ok","answer":"done"}}\' > "$HI_OUTPUT"\n'


def service(tmp_path, placement=None) -> Service:
    reg = Registry(tmp_path / "data")
    reg.put("providers", Provider("none", "https://example.invalid/v1", "sk-test"))
    reg.put("harnesses", Harness.from_folder(ECHO))
    return Service(tmp_path / "data", reg, placement or LocalPlacement())


def harness(svc, name, script):
    data = Harness.from_folder(ECHO).to_dict()
    data.update(name=name, scripts={"run.sh": script})
    svc.registry.put("harnesses", Harness.from_dict(data))


async def settled(svc, rid) -> Record:
    run = svc.live.get(rid)
    if run:
        await run.done.wait()
    return svc.get(rid)


def test_a_turn_is_recorded_end_to_end(tmp_path):
    async def go():
        svc = service(tmp_path)
        run = await svc.start(Ask("echo/m1", "say hi", instructions="be brief", metadata={"who": "t"},
                                  original={"input": "say hi"}))
        assert run.created.status == "running"
        r = await settled(svc, run.record.id)
        assert (r.status, r.exit_code, r.answer, r.session_id) == ("completed", 0, "echo: say hi", "echo-1")
        assert (r.harness, r.provider, r.sandbox, r.runtime, r.image) == ("echo", "none", "default", "local", None)
        assert r.files == ["hello.txt"] and r.base and r.commit and r.latency_s > 0 and r.request == {"input": "say hi"}
        assert b'"model":"m1"' in svc.output_path(r.id).read_bytes()
        assert [x.id for x in svc.list()] == [r.id]
    asyncio.run(go())


def test_a_conversation_continues_in_its_workspace_and_session(tmp_path):
    async def go():
        svc = service(tmp_path)
        first = await settled(svc, (await svc.start(Ask("echo", "one"))).record.id)
        second = await settled(svc, (await svc.start(Ask("echo", "two", previous_id=first.id))).record.id)
        assert second.workspace == first.workspace and second.previous_id == first.id
        assert b'"session_id_in":"echo-1"' in svc.output_path(second.id).read_bytes()
        with pytest.raises(Invalid, match="no response"):
            await svc.start(Ask("echo", "x", previous_id="resp_nope"))
        harness(svc, "other", "true\n")
        with pytest.raises(Invalid, match="stays on its harness"):
            await svc.start(Ask("other", "x", previous_id=first.id))
    asyncio.run(go())


def test_one_turn_at_a_time_per_conversation(tmp_path):
    async def go():
        svc = service(tmp_path)
        harness(svc, "slow", SLOW.format(s=1))
        first = await settled(svc, (await svc.start(Ask("slow", "one"))).record.id)
        second = await svc.start(Ask("slow", "two", previous_id=first.id))
        with pytest.raises(Conflict):
            await svc.start(Ask("slow", "three", previous_id=first.id))
        await settled(svc, second.record.id)
        third = await svc.start(Ask("slow", "three", previous_id=first.id))      # free once it's over
        assert (await settled(svc, third.record.id)).status == "completed"
    asyncio.run(go())


def test_a_turn_outlives_its_followers_and_late_followers_see_everything(tmp_path):
    async def go():
        svc = service(tmp_path)
        harness(svc, "slow", SLOW.format(s=1))
        run = await svc.start(Ask("slow", "x"))
        async for event in run.follow():
            break                                    # this follower leaves at once
        r = await settled(svc, run.record.id)
        assert r.status == "completed" and svc.output_path(r.id).read_bytes() == b"start\nend\n"
        late = b"".join([e.data async for e in run.follow()])
        assert late == b"start\nend\n"
    asyncio.run(go())


def test_cancel_running_and_while_setting_up(tmp_path):
    class SlowSetup(LocalPlacement):
        def runtime(self, resolved):
            class Waits:
                async def start(self, spec):
                    await asyncio.sleep(30)
            return Waits()

    async def go():
        svc = service(tmp_path)
        harness(svc, "slow", SLOW.format(s=30))
        run = await svc.start(Ask("slow", "x"))
        async for _ in run.follow():
            assert svc.cancel(run.record.id)
            break
        assert (await settled(svc, run.record.id)).status == "cancelled"
        assert not svc.cancel(run.record.id)         # over: nothing to cancel

        svc2 = service(tmp_path / "two", SlowSetup())
        run2 = await svc2.start(Ask("echo", "x"))
        assert svc2.get(run2.record.id).status == "running"      # visible before setup ends
        await asyncio.to_thread(svc2.cancel, run2.record.id)
        r = await settled(svc2, run2.record.id)
        assert (r.status, r.exit_code) == ("cancelled", None) and not svc2.output_path(r.id).exists()
    asyncio.run(go())


def test_a_failed_setup_and_a_failed_harness_are_told_apart(tmp_path):
    class Broken(LocalPlacement):
        def runtime(self, resolved):
            class Fails:
                async def start(self, spec):
                    return NeverStarted("sandbox 'default' failed to build")
            return Fails()

    async def go():
        svc = service(tmp_path, Broken())
        r = await settled(svc, (await svc.start(Ask("echo", "x"))).record.id)
        assert (r.status, r.error_code, r.error) == ("failed", "setup_failed", "sandbox 'default' failed to build")
        svc = service(tmp_path / "b")
        harness(svc, "exit3", "exit 3\n")
        r = await settled(svc, (await svc.start(Ask("exit3", "x"))).record.id)
        assert (r.status, r.error_code, r.exit_code) == ("failed", "harness_failed", 3)
    asyncio.run(go())


def test_turns_go_side_by_side(tmp_path):
    async def go():
        svc = service(tmp_path)
        harness(svc, "slow", SLOW.format(s=1))
        began = time.time()
        runs = [await svc.start(Ask("slow", str(i))) for i in range(4)]
        records = [await settled(svc, r.record.id) for r in runs]
        assert all(r.status == "completed" for r in records) and len({r.workspace for r in records}) == 4
        assert time.time() - began < 3
    asyncio.run(go())


def test_refusals_happen_before_anything_runs(tmp_path):
    async def go():
        svc = service(tmp_path)
        with pytest.raises(Invalid, match="no harness"):
            await svc.start(Ask("nope", "x"))
        harness(svc, "badtpl", "true\n")
        data = svc.registry.get("harnesses", "badtpl").to_dict()
        data["files"] = {"x": "{nope}"}
        svc.registry.put("harnesses", Harness.from_dict(data))
        with pytest.raises(Invalid, match="unknown placeholder"):
            await svc.start(Ask("badtpl", "x"))
        assert svc.list() == [] and svc.busy == set()
        with pytest.raises(NotFound):
            svc.get("resp_nope")
    asyncio.run(go())


def test_a_restart_closes_what_was_in_flight(tmp_path):
    async def go():
        svc = service(tmp_path)
        lost = Record(id="resp_lost0000000000", model="echo", harness="echo", provider="none", sandbox="default",
                      runtime="local", workspace="/nowhere")
        svc.records.put(lost.id, lost)
        await svc.recover()
        r = svc.get(lost.id)
        assert (r.status, r.error_code) == ("failed", "server_restarted")
    asyncio.run(go())
