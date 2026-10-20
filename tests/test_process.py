"""Layer 1: a process streams exactly what it writes, takes input or says it couldn't, stops gracefully
when asked, is killed when it won't, and leaves nothing running; the local runtime gives it only the
host variables on the allowlist."""
import asyncio
import sys
import time
from pathlib import Path

import pytest

from harness_interface.errors import Invalid
from harness_interface.execution import Outcome, Spec
from harness_interface.runtimes.local import LocalRuntime
from harness_interface.runtimes.process import host_env

PY = sys.executable

# Prints "child <pid>" and "ready" once it and its child both handle SIGINT, then "INT <pid>" from each
# on each SIGINT; with `exit_on_int` both exit 3 on the first. The child shows the signal reached the group.
ON_INT = r"""
import os, signal, subprocess, sys, time
def on_int(*_):
    os.write(1, f"INT {os.getpid()}\n".encode())     # not print: the signal may land inside one
    if EXIT_ON_INT:
        sys.exit(3)
signal.signal(signal.SIGINT, on_int)
if len(sys.argv) > 1:                                # the child: say it is ready on the fd it was given
    os.write(int(sys.argv[1]), b"r")
else:
    r, w = os.pipe()
    child = subprocess.Popen([sys.executable, "-c", f"EXIT_ON_INT = {EXIT_ON_INT}\n" + CODE, str(w)], pass_fds=[w])
    os.read(r, 1)
    print("child", child.pid, flush=True)
    print("ready", flush=True)
while True:
    time.sleep(0.05)
"""


def on_int(exit_on_int: bool, **kw) -> Spec:
    return Spec([PY, "-c", f"EXIT_ON_INT = {exit_on_int}\nCODE = {ON_INT!r}\n{ON_INT}"], **kw)


def py(code: str, **kw) -> Spec:
    return Spec([PY, "-c", code], **kw)


async def run(runtime, spec):
    """Start, collect every event by stream, and the outcome."""
    execution = await runtime.start(spec)
    out: dict[str, bytes] = {}
    async for event in execution.events():
        out[event.stream] = out.get(event.stream, b"") + event.data
    return out, await execution.wait()


class Stdout:
    """An execution's stdout, read as far as a test needs."""

    def __init__(self, execution):
        self.events, self.seen = execution.events(), bytearray()

    async def until(self, text: bytes) -> None:
        while text not in self.seen:
            event = await asyncio.wait_for(self.events.__anext__(), 10)
            if event.stream == "stdout":
                self.seen.extend(event.data)

    async def rest(self) -> str:
        async for event in self.events:
            if event.stream == "stdout":
                self.seen.extend(event.data)
        return self.seen.decode()


def go(coro):
    return asyncio.run(coro)


def gone(pid: int) -> bool:
    """Reaped, or a zombie waiting to be."""
    stat = Path(f"/proc/{pid}/stat")
    try:
        return stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"
    except FileNotFoundError:
        return True


def eventually_gone(pid: int) -> bool:
    deadline = time.time() + 5
    while not gone(pid) and time.time() < deadline:
        time.sleep(0.05)
    return gone(pid)


# ── output and input ───────────────────────────────────────────────────────────────────────────
def test_stdout_and_stderr_arrive_separately_and_exactly():
    code = "import sys; sys.stdout.buffer.write(b'\\xff\\x00out'); sys.stdout.flush(); sys.stderr.write('err\\n')"
    out, outcome = go(run(LocalRuntime(), py(code)))
    assert out == {"stdout": b"\xff\x00out", "stderr": b"err\n"} and outcome == Outcome.exited(0)


def test_output_streams_as_it_is_written():
    async def go_():
        e = await LocalRuntime().start(py("import time; print('first', flush=True); time.sleep(30)"))
        began = time.time()
        async for event in e.events():
            assert event.data.startswith(b"first") and time.time() - began < 5   # not held until the end
            break
        e.kill()
        assert await e.wait() == Outcome.killed()
    go(go_())


def test_input_is_written_then_closed():
    out, outcome = go(run(LocalRuntime(), Spec(["cat"], input=b"hello")))
    assert out["stdout"] == b"hello" and outcome.ok


def test_a_process_need_not_read_its_input():
    out, outcome = go(run(LocalRuntime(), Spec(["true"], input=b"x" * 2_000_000)))
    assert outcome.ok and out == {}


def test_more_input_while_it_runs():
    async def go_():
        e = await LocalRuntime().start(Spec(["cat"], input=b"one ", interactive=True))
        await e.send(b"two")
        await e.end_input()
        chunks = [ev.data async for ev in e.events()]
        assert b"".join(chunks) == b"one two" and (await e.wait()).ok
        with pytest.raises(Invalid):
            await e.send(b"after the end")
    go(go_())


def test_no_more_input_unless_asked_for():
    async def go_():
        e = await LocalRuntime().start(Spec(["cat"]))
        with pytest.raises(Invalid):
            await e.send(b"x")
        await e.wait()
    go(go_())


def test_input_it_no_longer_reads_is_refused_not_lost():
    async def go_():
        e = await LocalRuntime().start(py("import os, time; os.close(0); print('closed', flush=True); time.sleep(30)",
                                          interactive=True))
        await Stdout(e).until(b"closed")
        for _ in range(2):                           # refused, and refused again: never silently dropped
            with pytest.raises(Invalid):
                await e.send(b"a steer\n" * 10_000)
        e.kill()
        assert await e.wait() == Outcome.killed()
    go(go_())


def test_an_exit_code_is_reported_exactly():
    assert go(run(LocalRuntime(), py("raise SystemExit(3)")))[1] == Outcome.exited(3)


# ── stop, kill and timeout ─────────────────────────────────────────────────────────────────────
def test_a_stop_signals_the_whole_group_and_its_exit_is_stopped():
    async def go_():
        e = await LocalRuntime().start(on_int(True))
        out = Stdout(e)
        await out.until(b"ready")
        e.stop(10)
        return await out.rest(), await e.wait()
    out, outcome = go(go_())
    assert outcome == Outcome.stopped(3)
    lines = out.splitlines()
    child = next(int(line.split()[1]) for line in lines if line.startswith("child"))
    assert sum(line.startswith("INT") for line in lines) >= 1 and eventually_gone(child)


def test_a_stop_it_ignores_becomes_a_kill_of_the_whole_group():
    async def go_():
        e = await LocalRuntime().start(on_int(False))
        out = Stdout(e)
        await out.until(b"ready")
        began = time.time()
        e.stop(0.3)
        return await out.rest(), await e.wait(), time.time() - began
    out, outcome, took = go(go_())
    assert outcome == Outcome.killed() and took < 5
    child = next(int(line.split()[1]) for line in out.splitlines() if line.startswith("child"))
    assert eventually_gone(child)


def test_a_second_stop_brings_the_kill_closer_and_never_signals_twice():
    async def go_():
        e = await LocalRuntime().start(on_int(False))
        out = Stdout(e)
        await out.until(b"ready")
        began = time.time()
        e.stop(60)
        await out.until(b"INT")
        e.stop(0.2)
        e.stop(60)                                   # a later, longer stop does not push it back
        return await out.rest(), await e.wait(), time.time() - began
    out, outcome, took = go(go_())
    pid_lines = [line for line in out.splitlines() if line.startswith("INT")]
    assert outcome == Outcome.killed() and took < 5
    assert len(pid_lines) == len(set(pid_lines)) == 2              # the parent and its child, once each


def test_nothing_is_sent_after_a_stop():
    async def go_():
        e = await LocalRuntime().start(on_int(False, interactive=True))
        await Stdout(e).until(b"ready")
        e.stop(0.5)
        with pytest.raises(Invalid):
            await e.send(b"too late\n")
        return await e.wait()
    assert go(go_()) == Outcome.killed()


def test_a_timeout_kills_the_whole_process_group():
    code = "import subprocess; p = subprocess.Popen(['sleep', '30']); print(p.pid, flush=True); p.wait()"
    out, outcome = go(run(LocalRuntime(), py(code, timeout_s=0.5)))
    assert outcome == Outcome.timed_out() and eventually_gone(int(out["stdout"]))


def test_what_it_leaves_running_does_not_keep_it_open():
    began = time.time()
    out, outcome = go(run(LocalRuntime(), Spec(["sh", "-c", "sleep 30 & echo started"])))
    assert out["stdout"] == b"started\n" and outcome.ok and time.time() - began < 5


def test_a_kill_ends_it_at_once():
    async def go_():
        e = await LocalRuntime().start(Spec(["sleep", "30"]))
        e.kill()
        return await e.wait()
    assert go(go_()) == Outcome.killed()


def test_stop_and_kill_work_from_another_thread():
    async def go_():
        stopped = await LocalRuntime().start(on_int(True))
        await Stdout(stopped).until(b"ready")
        await asyncio.to_thread(stopped.stop, 10)
        killed = await LocalRuntime().start(Spec(["sleep", "30"]))
        await asyncio.to_thread(killed.kill)
        return await stopped.wait(), await killed.wait()
    assert go(go_()) == (Outcome.stopped(3), Outcome.killed())


def test_stop_and_kill_after_the_end_change_nothing():
    async def go_():
        e = await LocalRuntime().start(Spec(["true"]))
        assert (await e.wait()).ok
        e.stop(0)
        e.kill()
        await asyncio.sleep(0.05)
        assert (await e.wait()).ok
    go(go_())


def test_a_stop_timeout_must_not_be_negative():
    async def go_():
        e = await LocalRuntime().start(Spec(["true"]))
        with pytest.raises(Invalid):
            e.stop(-1)
        await e.wait()
    go(go_())


def test_cancelling_the_start_leaves_nothing_running():
    async def go_():
        task = asyncio.create_task(LocalRuntime().start(Spec(["sleep", "30"], input=b"x" * 2_000_000)))
        await asyncio.sleep(0.2)                     # spawned, and blocked writing input it never reads
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    began = time.time()
    go(go_())
    assert time.time() - began < 5


def test_waiting_never_waits_on_a_reader():
    async def go_():
        e = await LocalRuntime().start(py("import sys; sys.stdout.write('x' * 1_000_000)"))
        assert (await asyncio.wait_for(e.wait(), 10)).ok           # nobody read its output, and it still ended
        assert sum([len(ev.data) async for ev in e.events()]) == 1_000_000
    go(go_())


def test_events_can_be_iterated_once():
    async def go_():
        e = await LocalRuntime().start(Spec(["true"]))
        [_ async for _ in e.events()]
        with pytest.raises(AssertionError):
            [_ async for _ in e.events()]
        await e.wait()
    go(go_())


def test_a_program_that_does_not_exist_never_starts():
    _, outcome = go(run(LocalRuntime(), Spec(["no-such-program-anywhere"])))
    assert outcome.kind == "failed" and "no-such-program-anywhere" in outcome.reason


def test_runs_go_side_by_side():
    async def go_():
        began = time.time()
        results = await asyncio.gather(*(run(LocalRuntime(), Spec(["sleep", "1"])) for _ in range(4)))
        assert all(o.ok for _, o in results) and time.time() - began < 3
    go(go_())


# ── the local runtime's environment ────────────────────────────────────────────────────────────
def test_it_runs_in_its_workspace_with_its_environment(tmp_path):
    out, _ = go(run(LocalRuntime(), py("import os; print(os.getcwd(), os.environ['WHO'], bool(os.environ.get('PATH')))",
                                         env={"WHO": "me"}, workspace=tmp_path)))
    assert out["stdout"].decode().split() == [str(tmp_path), "me", "True"]


def test_only_allowlisted_host_variables_reach_it(monkeypatch):
    for name in ("EXT_ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "SOMETHING"):
        monkeypatch.setenv(name, "sk-host-secret")
    monkeypatch.setenv("LANG", "C.UTF-8")
    out, _ = go(run(LocalRuntime(), py("import os, json; print(json.dumps(dict(os.environ)))", env={"LANG": "mine"})))
    seen = __import__("json").loads(out["stdout"])
    assert "sk-host-secret" not in out["stdout"].decode()
    assert seen["LANG"] == "mine" and "PATH" in seen                # the spec wins; the allowlist passes
    assert "sk-host-secret" not in host_env().values()
