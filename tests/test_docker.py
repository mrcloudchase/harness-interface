"""Layer 1, against a fake docker: every run is hardened, reaches out only through its own door, gets
its environment by name from an allowlist, holds at most a token, stops by SIGINT and is killed when
it must, and leaves nothing behind on any path; images are built once per Dockerfile."""
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from harness_interface.execution import Outcome, Spec
from harness_interface.runtimes.docker import (DOOR_IMAGE, HARDENING, KEY_PATH, LOCKDOWN, DockerRuntime, Images,
                                               Provider, sweep)

FAKES = Path(__file__).parent / "fakes"
KEY = "sk-real-provider-key"
IMAGE = "hi-test:0123456789ab"
ANTHROPIC = Provider("https://api.deepseek.com/anthropic", "anthropic-messages", KEY, token="sk-ant-api03-hi-token")


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    state = tmp_path / "docker"
    state.mkdir()
    monkeypatch.setenv("PATH", f"{FAKES}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_CONFIG", str(state))                       # the fake keeps its state there
    monkeypatch.setenv("EXT_ANTHROPIC_API_KEY", "sk-from-the-host")        # as on this machine: never passed on
    monkeypatch.setattr("harness_interface.runtimes.docker.SECRETS", tmp_path / "shm")
    (tmp_path / "shm").mkdir()
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

    def run(self) -> list[str]:
        return next(c for c in self.calls() if c[0] == "run" and "hi-run-" in c[c.index("--name") + 1])

    def door(self) -> list[str]:
        return next(c for c in self.calls() if c[0] == "run" and "hi-door-" in c[c.index("--name") + 1])

    def name(self, call: list[str]) -> str:
        return call[call.index("--name") + 1]

    def client_env(self, call: list[str]) -> dict:
        return json.loads((self.state / f"{self.name(call)}.client-env").read_text())

    def torn_down(self) -> bool:
        calls = self.calls()
        made = {self.name(c) for c in calls if c[0] == "run"}
        removed = {n for c in calls if c[:2] == ["rm", "-f"] for n in c[2:]}
        networks = {c[3] for c in calls if c[:3] == ["network", "create", "--internal"]}
        gone = {n for c in calls if c[:3] == ["network", "rm", "-f"] for n in c[3:]}
        return made <= removed and networks <= gone


READY = "import time; print('ready', flush=True); time.sleep(30)"


def py(code: str, **kw) -> Spec:
    return Spec([sys.executable, "-c", code], **kw)


async def run(runtime, spec):
    execution = await runtime.start(spec)
    out: dict[str, bytes] = {}
    async for event in execution.events():
        out[event.stream] = out.get(event.stream, b"") + event.data
    return out, await execution.wait()


def go(coro):
    return asyncio.run(coro)


def values(call: list[str], flag: str) -> list[str]:
    return [call[i + 1] for i, a in enumerate(call) if a == flag]


# ── the run ────────────────────────────────────────────────────────────────────────────────────
def test_every_run_is_hardened_with_its_paths_the_same_inside(fake_docker, tmp_path):
    ws, tools, rundir = tmp_path / "ws", tmp_path / "tools", tmp_path / "rundir"
    for d in (ws, tools, rundir):
        d.mkdir()
    rt = DockerRuntime(IMAGE, read_only=[tools], writable=[rundir])
    _, outcome = go(run(rt, Spec(["sh", "-c", "true"], workspace=ws)))
    the_run = fake_docker.run()
    assert outcome.ok and the_run[:4] == ["run", "--rm", "-i", "--init"]
    assert "TINI_KILL_PROCESS_GROUP=1" in values(the_run, "-e")
    assert " ".join(HARDENING) in " ".join(the_run)
    assert {f"{ws}:{ws}", f"{tools}:{tools}:ro", f"{rundir}:{rundir}"} <= set(values(the_run, "-v"))
    assert values(the_run, "-w") == [str(ws)] and the_run[-4:] == [IMAGE, "sh", "-c", "true"]
    network = values(the_run, "--network")[0]
    assert ["network", "create", "--internal", network] in fake_docker.calls() and fake_docker.torn_down()


def test_the_run_is_the_workspace_owners(fake_docker, monkeypatch):
    import harness_interface.runtimes.docker as d
    monkeypatch.setattr(d.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(d.os, "getuid", lambda: 1001)
    monkeypatch.setattr(d.os, "getgid", lambda: 121)
    go(run(DockerRuntime(IMAGE), Spec(["true"])))
    assert values(fake_docker.run(), "--user") == ["1001:121"]   # not root: the server's own user owns the workspace


def test_as_root_the_run_is_uid_1000_and_owns_what_it_writes(fake_docker, tmp_path, monkeypatch):
    import harness_interface.runtimes.docker as d
    owned = []
    monkeypatch.setattr(d.os, "geteuid", lambda: 0)
    monkeypatch.setattr(d.os, "lchown", lambda p, u, g: owned.append((str(p), u, g)))
    monkeypatch.setattr(d.os, "chown", lambda p, u, g: owned.append((str(p), u, g)))
    ws, rundir = tmp_path / "ws", tmp_path / "rundir"
    (ws / "src").mkdir(parents=True)
    rundir.mkdir()
    go(run(DockerRuntime(IMAGE, writable=[rundir]), Spec(["true"], workspace=ws)))
    assert values(fake_docker.run(), "--user") == ["1000:1000"]
    assert {(str(ws), 1000, 1000), (str(ws / "src"), 1000, 1000), (str(rundir), 1000, 1000)} <= set(owned)


def test_the_environment_goes_by_name_and_only_what_the_spec_gives(fake_docker, tmp_path):
    spec = py("import os, json; print(json.dumps(dict(os.environ)))", env={"SECRET_KEY": "sk-shh", "HOME": "/ws/.home"})
    out, outcome = go(run(DockerRuntime(IMAGE), spec))
    inside = json.loads(out["stdout"])
    assert outcome.ok and inside["SECRET_KEY"] == "sk-shh" and inside["HOME"] == "/ws/.home"   # arrived, by name
    assert "EXT_ANTHROPIC_API_KEY" not in inside
    assert set(inside) - {"PATH", "LC_CTYPE"} == {"SECRET_KEY", "HOME", "TINI_KILL_PROCESS_GROUP", "HTTPS_PROXY",
                                                 "https_proxy", "NO_PROXY", "no_proxy"}   # LC_CTYPE: Python's own
    assert inside["HTTPS_PROXY"] == "http://hi-door:3128" and "hi-provider" in inside["NO_PROXY"].split(",")
    assert not any("sk-shh" in arg for c in fake_docker.calls() for arg in c)     # never on a command line
    for call in (fake_docker.run(), fake_docker.door()):
        assert "EXT_ANTHROPIC_API_KEY" not in fake_docker.client_env(call)     # nor in any Docker client


def test_a_spec_cannot_point_the_docker_client_elsewhere(fake_docker, tmp_path):
    planted = {"PATH": "/nowhere", "HOME": str(tmp_path / "planted"), "DOCKER_HOST": "tcp://elsewhere:2375"}
    _, outcome = go(run(DockerRuntime(IMAGE), Spec([sys.executable, "-c", "pass"], env=planted)))
    client = fake_docker.client_env(fake_docker.run())
    assert outcome.ok and client["PATH"] == os.environ["PATH"] and client["HOME"] == os.environ["HOME"]
    assert client["DOCKER_CONFIG"] == str(fake_docker.state) and "DOCKER_HOST" not in client
    assert {f"{k}={v}" for k, v in planted.items()} <= set(values(fake_docker.run(), "-e"))   # the run still gets them


# ── the door ───────────────────────────────────────────────────────────────────────────────────
def test_the_door_is_locked_down_and_allows_exactly_its_hosts(fake_docker):
    rt = DockerRuntime(IMAGE, egress=["pypi.org", "https://api.example.com/v1"])
    go(run(rt, Spec(["true"])))
    door, the_run = fake_docker.door(), fake_docker.run()
    assert " ".join(LOCKDOWN) in " ".join(door) and values(door, "--user") == ["65534:65534"]
    assert values(door, "--network") == values(the_run, "--network")
    assert set(values(door, "--network-alias")) == {"hi-door", "hi-provider"}
    assert door[door.index(DOOR_IMAGE) + 1:] == ["python3", "/door/door.py", "0.0.0.0:3128",
                                                 "api.example.com:443", "pypi.org:443"]
    calls = fake_docker.calls()
    assert calls.index(["network", "connect", "bridge", fake_docker.name(door)]) < calls.index(the_run)


def test_under_the_gateway_the_key_reaches_only_the_doors_stdin(fake_docker):
    rt = DockerRuntime(IMAGE, egress=["pypi.org"], provider=ANTHROPIC)
    assert rt.provider_url == "http://hi-provider:8080/anthropic" and rt.key_path == KEY_PATH
    assert DockerRuntime(IMAGE).provider_url is None and DockerRuntime(IMAGE).key_path is None
    holder = {}

    async def go_():
        e = await rt.start(py(READY, env={"HI_PROVIDER_KEY_FILE": str(KEY_PATH)}))
        await e.events().__anext__()                 # it runs: everything is in place
        source = key_source(fake_docker.run())
        holder.update(content=source.read_text(), mode=stat.S_IMODE(source.stat().st_mode), source=source)
        e.kill()
        return await e.wait()
    assert go(go_()) == Outcome.killed()
    door = fake_docker.door()
    assert door[door.index(DOOR_IMAGE) + 1:] == ["python3", "/door/door.py", "0.0.0.0:3128", "pypi.org:443",
                                                 "--gateway", "0.0.0.0:8080", ANTHROPIC.url, "anthropic-messages"]
    assert (fake_docker / f"{fake_docker.name(door)}.stdin").read_text() == f"{ANTHROPIC.token}\n{KEY}\n"
    assert holder["content"] == ANTHROPIC.token and holder["mode"] == 0o400   # the sandbox holds only the token
    assert not holder["source"].exists() and not any(Path(fake_docker.state.parent / "shm").iterdir())
    for call in fake_docker.calls():
        assert not any(KEY in arg for arg in call)
    for path in fake_docker.state.glob("*.client-env"):
        assert KEY not in path.read_text()


def key_source(call: list[str]) -> Path:
    """The host file mounted as the sandbox's credential."""
    return Path(next(v.split(":")[0] for v in values(call, "-v") if v.endswith(f":{KEY_PATH}:ro")))


def test_in_file_mode_the_door_tunnels_to_the_provider_and_the_sandbox_reads_the_key(fake_docker):
    provider = Provider("https://api.openai.com/v1", "openai-responses", KEY, credential="file")
    rt = DockerRuntime(IMAGE, provider=provider)
    assert rt.provider_url == "https://api.openai.com/v1"
    seen = {}

    async def go_():
        e = await rt.start(py(READY))
        await e.events().__anext__()
        seen["source"] = key_source(fake_docker.run())
        seen["content"] = seen["source"].read_text()
        e.kill()
        return await e.wait()
    assert go(go_()) == Outcome.killed()
    door = fake_docker.door()
    assert door[door.index(DOOR_IMAGE) + 1:] == ["python3", "/door/door.py", "0.0.0.0:3128", "api.openai.com:443"]
    assert (fake_docker / f"{fake_docker.name(door)}.stdin").read_text() == ""
    assert seen["content"] == KEY and not seen["source"].exists() and fake_docker.torn_down()


def test_what_the_door_decides_arrives_as_door_events(fake_docker):
    (fake_docker / "door-log").write_text("door deny github.com:443\n")
    out, outcome = go(run(DockerRuntime(IMAGE), py("import time; time.sleep(0.5); print('done')")))
    assert outcome.ok and out["stdout"] == b"done\n" and b"door deny github.com:443" in out["door"]


def test_a_dead_door_never_starts_and_leaves_nothing(fake_docker):
    (fake_docker / "door-dead").touch()
    _, outcome = go(run(DockerRuntime(IMAGE, provider=ANTHROPIC), Spec(["true"])))
    assert outcome.kind == "failed" and "door did not start" in outcome.reason and "image is missing" in outcome.reason
    assert not any(c[0] == "run" and "hi-run-" in " ".join(c) for c in fake_docker.calls())
    assert fake_docker.torn_down() and not any(Path(fake_docker.state.parent / "shm").iterdir())


def test_a_provider_is_whole_and_never_shown_with_its_key():
    assert KEY not in repr(ANTHROPIC) and ANTHROPIC.token not in repr(ANTHROPIC)
    for bad in (dict(url="http://api.example.com", api="openai-chat"),
                dict(url="https://api.example.com", api="openai-websocket"),
                dict(url="https://api.example.com", api="openai-chat", credential="env"),
                dict(url="https://api.example.com", api="openai-chat", key="two\nlines"),
                dict(url="https://api.example.com", api="openai-chat", key=""),
                dict(url="https://api.example.com", api="openai-chat", token="")):
        with pytest.raises(ValueError):
            Provider(**{"key": KEY, "token": "t", **bad})


# ── stop, kill, timeout and teardown ───────────────────────────────────────────────────────────
STUBBORN = ("import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\n"
            "print('ready', flush=True)\ntime.sleep(30)")
GRACEFUL = ("import signal, sys, time\nsignal.signal(signal.SIGINT, lambda *_: sys.exit(0))\n"
            "print('ready', flush=True)\ntime.sleep(30)")


async def ready_then(rt, code: str, act) -> Outcome:
    e = await rt.start(py(code))
    events = e.events()
    while b"ready" not in (await events.__anext__()).data:
        pass
    act(e)
    async for _ in events:
        pass
    return await e.wait()


def test_a_stop_is_a_sigint_through_docker(fake_docker):
    assert go(ready_then(DockerRuntime(IMAGE), GRACEFUL, lambda e: e.stop(10))) == Outcome.stopped(0)
    run_name = fake_docker.name(fake_docker.run())
    assert ["kill", "--signal", "INT", run_name] in fake_docker.calls() and fake_docker.torn_down()


def test_a_stop_asked_for_as_it_starts_still_lands(fake_docker):
    (fake_docker / "slow-create").touch()

    async def go_():
        e = await DockerRuntime(IMAGE).start(py(GRACEFUL))
        e.stop(10)                                   # before its container exists
        return await e.wait()
    assert go(go_()).kind == "stopped"


def test_a_stop_it_ignores_becomes_a_docker_kill(fake_docker):
    assert go(ready_then(DockerRuntime(IMAGE), STUBBORN, lambda e: e.stop(0.2))) == Outcome.killed()
    assert ["kill", fake_docker.name(fake_docker.run())] in fake_docker.calls() and fake_docker.torn_down()


def test_a_kill_the_container_does_not_take_still_ends_the_run(fake_docker):
    (fake_docker / "kill-fails").touch()
    assert go(ready_then(DockerRuntime(IMAGE), STUBBORN, lambda e: e.kill())) == Outcome.killed()
    assert fake_docker.torn_down()


def test_a_timeout_kills_and_leaves_nothing(fake_docker):
    _, outcome = go(run(DockerRuntime(IMAGE), Spec(["sleep", "30"], timeout_s=0.5)))
    assert outcome == Outcome.timed_out() and fake_docker.torn_down()


def test_cancelled_during_setup_leaves_nothing(fake_docker):
    async def go_():
        task = asyncio.create_task(DockerRuntime(IMAGE, provider=ANTHROPIC).start(Spec(["sleep", "30"])))
        while not any(c[:2] == ["network", "create"] for c in fake_docker.calls()):
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    go(go_())
    assert not any(c[0] == "run" and "hi-run-" in " ".join(c) for c in fake_docker.calls())
    assert fake_docker.torn_down() and not any(Path(fake_docker.state.parent / "shm").iterdir())


def test_cancelled_while_the_door_is_created_leaves_no_door(fake_docker):
    (fake_docker / "slow-create").touch()

    async def go_():
        task = asyncio.create_task(DockerRuntime(IMAGE, provider=ANTHROPIC).start(Spec(["sleep", "30"])))
        while not list(fake_docker.state.glob("hi-door-*.client-pid")):
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    go(go_())
    [client] = fake_docker.state.glob("hi-door-*.client-pid")
    with pytest.raises(ProcessLookupError):          # its client is gone, so no door appears after the sweep
        os.kill(int(client.read_text()), 0)
    assert fake_docker.torn_down()


def test_cancelled_while_writing_the_credential_leaves_no_credential(fake_docker, monkeypatch):
    import threading
    entered, prepare = threading.Event(), DockerRuntime._prepare

    def slow_prepare(self, spec, names):
        entered.set()
        threading.Event().wait(0.3)                  # still writing when the cancel comes
        prepare(self, spec, names)
    monkeypatch.setattr(DockerRuntime, "_prepare", slow_prepare)

    async def go_():
        task = asyncio.create_task(DockerRuntime(IMAGE, provider=ANTHROPIC).start(Spec(["sleep", "30"])))
        await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    go(go_())
    assert not any(Path(fake_docker.state.parent / "shm").iterdir())


def test_the_sweep_removes_only_what_runs_left(fake_docker, tmp_path):
    (fake_docker / "leftovers").touch()
    left = tmp_path / "shm" / "hi-0123456789ab"
    left.mkdir()
    (left / "key").write_text(KEY)
    (tmp_path / "shm" / "someone-elses").mkdir()
    go(sweep())
    calls = fake_docker.calls()
    assert ["ps", "-aq", "--filter", "name=^hi-run-", "--filter", "name=^hi-door-"] in calls
    assert ["rm", "-f", "leftover-1", "leftover-2"] in calls and ["network", "rm", "leftover-1", "leftover-2"] in calls
    assert not left.exists() and (tmp_path / "shm" / "someone-elses").exists()


def test_no_docker_is_a_clear_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))                          # nowhere to find docker
    _, outcome = go(run(DockerRuntime(IMAGE), Spec(["true"])))
    assert outcome.kind == "failed" and "Docker is not installed" in outcome.reason
    with pytest.raises(RuntimeError, match="not installed"):
        go(sweep())


# ── images ─────────────────────────────────────────────────────────────────────────────────────
def test_an_image_is_built_once_per_dockerfile(fake_docker, tmp_path):
    images = Images(tmp_path / "logs")

    async def go_():
        return await asyncio.gather(*(images.ensure("box", "FROM scratch\n") for _ in range(3)))
    tags = go(go_())
    assert len(set(tags)) == 1 and tags[0].startswith("hi-box:")
    assert sum(c[0] == "build" for c in fake_docker.calls()) == 1
    assert Images.tag("box", "FROM scratch\n") != Images.tag("box", "FROM other\n")


def test_a_failed_build_says_why_and_is_logged(fake_docker, tmp_path):
    (fake_docker / "fail-build").touch()
    with pytest.raises(RuntimeError, match="boom"):
        go(Images(tmp_path / "logs").ensure("box", "FROM scratch\n"))
    assert "boom" in next((tmp_path / "logs").iterdir()).read_text()
