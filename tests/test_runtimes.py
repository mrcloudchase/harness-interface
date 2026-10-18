"""Layer 1: processes stream exactly what they write, take input, time out and cancel cleanly; the
Docker runtime hardens every run, never puts a secret on a command line, and leaves nothing behind;
the egress door lets through only what it is told to."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from harness_interface.errors import Invalid
from harness_interface.execution import Outcome, Spec
from harness_interface.runtimes import Docker, DockerRuntime, LocalRuntime, Sandbox
from harness_interface.runtimes.docker import HARDENING, LOCKDOWN, PREFIX
from harness_interface.runtimes.egress import Door, normalize

PY = sys.executable
FAKES = Path(__file__).parent / "fakes"


def py(code: str, **kw) -> Spec:
    return Spec([PY, "-c", code], **kw)


async def run(runtime, spec):
    """Start, collect every event by stream, and the outcome."""
    execution = await runtime.start(spec)
    out: dict[str, bytes] = {}
    async for event in execution.events():
        out[event.stream] = out.get(event.stream, b"") + event.data
    return out, await execution.wait()


def go(coro):
    return asyncio.run(coro)


# ── a process, on the local runtime ────────────────────────────────────────────────────────────
def test_stdout_and_stderr_arrive_separately_and_exactly():
    code = "import sys; sys.stdout.buffer.write(b'\\xff\\x00out'); sys.stdout.flush(); sys.stderr.write('err\\n')"
    out, outcome = go(run(LocalRuntime(), py(code)))
    assert out == {"stdout": b"\xff\x00out", "stderr": b"err\n"} and outcome == Outcome.exited(0)


def test_output_streams_as_it_is_written():
    async def go_():
        e = await LocalRuntime().start(py("import sys,time; print('first', flush=True); time.sleep(2); print('second')"))
        began = time.time()
        async for event in e.events():
            assert event.data.startswith(b"first") and time.time() - began < 1.5   # not held until the end
            break
        e.cancel()
        await e.wait()
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


def test_an_exit_code_is_reported_exactly():
    assert go(run(LocalRuntime(), py("raise SystemExit(3)")))[1] == Outcome.exited(3)


def test_a_timeout_stops_the_whole_process_group():
    code = "import subprocess,sys; p=subprocess.Popen(['sleep','30']); print(p.pid, flush=True); p.wait()"
    out, outcome = go(run(LocalRuntime(), py(code, timeout_s=1)))
    assert outcome == Outcome.timed_out()
    child = int(out["stdout"])

    def gone() -> bool:                              # reaped, or a zombie waiting to be
        return not Path(f"/proc/{child}").exists() or "Z" in Path(f"/proc/{child}/stat").read_text().split()[2]
    deadline = time.time() + 5
    while not gone() and time.time() < deadline:
        time.sleep(0.05)
    assert gone()


def test_cancel_from_another_thread():
    async def go_():
        e = await LocalRuntime().start(Spec(["sleep", "30"]))
        await asyncio.to_thread(e.cancel)
        assert await e.wait() == Outcome.cancelled()
    go(go_())


def test_cancel_after_the_end_changes_nothing():
    async def go_():
        e = await LocalRuntime().start(Spec(["true"]))
        assert (await e.wait()).ok
        e.cancel()
        assert (await e.wait()).ok
    go(go_())


def test_cancelling_the_start_leaves_nothing_running():
    async def go_():
        task = asyncio.create_task(LocalRuntime().start(Spec(["sleep", "30"])))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    go(go_())


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


def test_it_runs_in_its_workspace_with_its_environment(tmp_path):
    out, _ = go(run(LocalRuntime(), py("import os; print(os.getcwd(), os.environ['WHO'], bool(os.environ.get('PATH')))",
                                         env={"WHO": "me"}, workspace=tmp_path)))
    assert out["stdout"].decode().split() == [str(tmp_path), "me", "True"]


def test_a_program_that_does_not_exist_never_starts():
    _, outcome = go(run(LocalRuntime(), Spec(["no-such-program-anywhere"])))
    assert outcome.kind == "failed" and "no-such-program-anywhere" in outcome.reason


def test_runs_go_side_by_side():
    async def go_():
        began = time.time()
        results = await asyncio.gather(*(run(LocalRuntime(), Spec(["sleep", "1"])) for _ in range(4)))
        assert all(o.ok for _, o in results) and time.time() - began < 3
    go(go_())


# ── the Docker runtime, against a fake docker ──────────────────────────────────────────────────
@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    state = tmp_path / "docker"
    state.mkdir()
    monkeypatch.setenv("PATH", f"{FAKES}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_DIR", str(state))
    (FAKES / "docker").chmod(0o755)

    return FakeDocker(state)


class FakeDocker:
    """The fake's state directory, and every call it was given."""

    def __init__(self, state: Path):
        self.state = state

    def __truediv__(self, name: str) -> Path:
        return self.state / name

    def calls(self) -> list[list[str]]:
        p = self.state / "calls"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


SANDBOX = Sandbox("box", "FROM scratch\n", egress=("pypi.org",))


def docker_runtime(tmp_path, **kw):
    return DockerRuntime(Docker(tmp_path / "logs"), SANDBOX, **kw)


def torn_down(calls) -> bool:
    runs = {c[c.index("--name") + 1] for c in calls if c[0] == "run" and "-d" not in c}
    removed = {n for c in calls if c[:2] == ["rm", "-f"] for n in c[2:]}
    nets = {n for c in calls if c[:3] == ["network", "rm", "-f"] for n in c[3:]}
    return runs <= removed and {r.replace("run-", "net-") for r in runs} <= nets


def test_every_run_is_hardened_and_secrets_stay_off_the_command_line(fake_docker, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    scripts = tmp_path / "scripts"
    spec = Spec(["sh", "-c", "echo $SECRET_KEY"], env={"SECRET_KEY": "sk-shh"}, workspace=ws)
    out, outcome = go(run(docker_runtime(tmp_path, egress=["https://api.example.com/v1"], mounts=[scripts]), spec))
    assert out["stdout"] == b"sk-shh\n" and outcome.ok                # the value arrived, by name
    calls = fake_docker.calls()
    assert not any("sk-shh" in arg for c in calls for arg in c)       # and never on a command line
    the_run = next(c for c in calls if c[0] == "run" and "-d" not in c)
    assert all(flag in the_run for flag in HARDENING)
    assert f"{ws}:{ws}" in the_run and f"{scripts}:{scripts}:ro" in the_run and str(ws) == the_run[the_run.index("-w") + 1]
    door = next(c for c in calls if c[0] == "run" and "-d" in c)
    assert all(flag in door for flag in LOCKDOWN)
    assert door[-2:] == ["api.example.com:443", "pypi.org:443"]       # exactly the allowlist
    assert ["network", "create", "--internal"] == next(c for c in calls if c[:2] == ["network", "create"])[:3]
    assert torn_down(calls)


def test_the_run_is_the_workspace_owners(fake_docker, tmp_path, monkeypatch):
    import harness_interface.runtimes.docker as d
    monkeypatch.setattr(d.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(d.os, "getuid", lambda: 1001)
    monkeypatch.setattr(d.os, "getgid", lambda: 121)
    go(run(docker_runtime(tmp_path), Spec(["true"])))
    the_run = next(c for c in fake_docker.calls() if c[0] == "run" and "-d" not in c)
    assert the_run[the_run.index("--user") + 1] == "1001:121"   # not root: the server's own user owns the workspace


def test_the_image_is_built_once_per_dockerfile(fake_docker, tmp_path):
    rt = docker_runtime(tmp_path)

    async def go_():
        await asyncio.gather(*(run(rt, Spec(["true"])) for _ in range(3)))
    go(go_())
    assert sum(c[0] == "build" for c in fake_docker.calls()) == 1
    assert SANDBOX.tag != Sandbox("box", "FROM other\n").tag


def test_a_failed_build_never_starts_and_is_logged(fake_docker, tmp_path):
    (fake_docker / "fail-build").touch()
    _, outcome = go(run(docker_runtime(tmp_path), Spec(["true"])))
    assert outcome.kind == "failed" and "boom" in outcome.reason
    assert "boom" in next((tmp_path / "logs").iterdir()).read_text()


def test_a_dead_door_never_starts_and_leaves_nothing(fake_docker, tmp_path):
    (fake_docker / "door-dead").touch()
    _, outcome = go(run(docker_runtime(tmp_path), Spec(["true"])))
    assert outcome.kind == "failed" and "egress door did not start" in outcome.reason
    calls = fake_docker.calls()
    assert not any(c[0] == "run" and "-d" not in c for c in calls)
    assert any(c[:2] == ["rm", "-f"] for c in calls) and any(c[:3] == ["network", "rm", "-f"] for c in calls)


@pytest.mark.parametrize("ending", ["cancel", "timeout"])
def test_cancel_and_timeout_leave_nothing(fake_docker, tmp_path, ending):
    async def go_():
        e = await docker_runtime(tmp_path).start(Spec(["sleep", "30"], timeout_s=1 if ending == "timeout" else None))
        if ending == "cancel":
            e.cancel()
        return await e.wait()
    outcome = go(go_())
    assert outcome == (Outcome.cancelled() if ending == "cancel" else Outcome.timed_out())
    calls = fake_docker.calls()
    assert any(c[0] == "kill" for c in calls) and torn_down(calls)


def test_cancelled_during_setup_leaves_nothing(fake_docker, tmp_path):
    (fake_docker / "images").write_text(SANDBOX.tag)

    async def go_():
        task = asyncio.create_task(docker_runtime(tmp_path).start(Spec(["sleep", "30"])))
        while not any(c[:2] == ["network", "create"] for c in fake_docker.calls()):
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    go(go_())
    calls = fake_docker.calls()
    assert not any(c[0] == "run" and "-d" not in c for c in calls)    # the run never started
    assert any(c[:3] == ["network", "rm", "-f"] for c in calls)


def test_recovery_removes_only_what_runs_left(fake_docker, tmp_path):
    (fake_docker / "leftovers").touch()
    go(Docker(tmp_path / "logs").recover())
    calls = fake_docker.calls()
    assert ["ps", "-aq", "--filter", f"name={PREFIX}run-", "--filter", f"name={PREFIX}door-"] in calls
    assert ["rm", "-f", "leftover-1", "leftover-2"] in calls and ["network", "rm", "leftover-1", "leftover-2"] in calls


def test_no_docker_is_a_clear_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))                          # nowhere to find docker
    _, outcome = go(run(docker_runtime(tmp_path), Spec(["true"])))
    assert outcome.kind == "failed" and "Docker is not installed" in outcome.reason
    with pytest.raises(RuntimeError, match="not installed"):
        go(Docker(tmp_path).recover())


# ── the egress door ────────────────────────────────────────────────────────────────────────────
def test_normalize():
    assert normalize("api.deepseek.com") == "api.deepseek.com:443"
    assert normalize("https://api.deepseek.com/anthropic") == "api.deepseek.com:443"
    assert normalize("http://localhost:8080/v1") == "localhost:8080"
    assert normalize("Host.Example:8443") == "host.example:8443"


async def _request(port: int, head: bytes, then: bytes = b"") -> bytes:
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(head)
    await w.drain()
    status = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), timeout=5)
    if status.startswith(b"HTTP/1.1 200") and then:
        w.write(then)
        await w.drain()
        status += await asyncio.wait_for(r.read(4096), timeout=5)
    w.close()
    return status


def test_the_door_tunnels_the_allowed_and_refuses_the_rest():
    async def go_():
        async def upstream(reader, writer):          # a plain TCP echo, standing in for a provider
            writer.write(b"upstream saw " + await reader.read(100))
            await writer.drain()
            writer.close()
        up = await asyncio.start_server(upstream, "127.0.0.1", 0)
        up_port = up.sockets[0].getsockname()[1]
        door = await Door([f"127.0.0.1:{up_port}", "127.0.0.1:1"]).serve("127.0.0.1", 0)
        port = door.sockets[0].getsockname()[1]
        async with up, door:
            ok = await _request(port, f"CONNECT 127.0.0.1:{up_port} HTTP/1.1\r\n\r\n".encode(), b"\x00\xffhello")
            assert ok.startswith(b"HTTP/1.1 200") and ok.endswith(b"upstream saw \x00\xffhello")   # bytes untouched
            for head in (b"CONNECT 127.0.0.1:9 HTTP/1.1\r\n\r\n",                  # another port
                         b"CONNECT example.com:443 HTTP/1.1\r\n\r\n",              # another host
                         b"GET http://127.0.0.1:%d/ HTTP/1.1\r\n\r\n" % up_port,   # not a tunnel
                         b"GET / HTTP/1.1\r\nHost: door\r\n\r\n"):                # the door itself
                assert (await _request(port, head)).startswith(b"HTTP/1.1 403")
            assert (await _request(port, b"CONNECT 127.0.0.1:1 HTTP/1.1\r\n\r\n")).startswith(b"HTTP/1.1 502")
    go(go_())
