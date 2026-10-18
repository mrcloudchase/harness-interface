"""What the Docker runtime would run, without a daemon: the image tag, the door, the container."""
from pathlib import Path

import pytest

from harness_interface.models import Sandbox
from harness_interface.runner import Prepared
from harness_interface.docker import DOOR_PORT, HARDENING, LOCKDOWN, DockerNames, DockerRuntime
from harness_interface.runtime import Job


def test_image_tag_follows_the_dockerfile_content():
    a, b = Sandbox(name="s", dockerfile="FROM a"), Sandbox(name="s", dockerfile="FROM b")
    assert DockerRuntime.tag(a) != DockerRuntime.tag(b) and DockerRuntime.tag(a) == DockerRuntime.tag(Sandbox(name="s", dockerfile="FROM a"))
    assert DockerRuntime.tag(a).startswith("harness-interface/s:")


def test_run_and_door_argv(tmp_path):
    sb = DockerRuntime(tmp_path)
    assert sb.mounts(Path("/x"), Path("/y")).workspace == "/workspace"
    prepared = Prepared(argv=["bash", "/harness/run.sh"], env={"HI_TASK": "t", "HI_PROVIDER_KEY": "k", "HOME": "/workspace/.home"},
                        stdin=b"{}", timeout_s=9)
    job = Job(id="abc", prepared=prepared, workspace=Path("/ws"), harness_dir=Path("/hd"), log_path=tmp_path / "l",
              image="harness-interface/default:deadbeef", egress=["api.deepseek.com:443", "pypi.org:443"])
    names = DockerNames.of("abc")
    argv = sb.run_argv(job, names)
    assert argv[:2] == ["docker", "run"] and argv[-3:] == ["harness-interface/default:deadbeef", "bash", "/harness/run.sh"]
    assert "--network" in argv and argv[argv.index("--network") + 1] == "harness-net-abc"
    assert "--runtime" not in argv
    assert "/tmp:rw,exec,nosuid,nodev,size=512m" in argv                 # native modules load from /tmp
    assert all(flag in argv for flag in HARDENING)
    assert "/ws:/workspace" in argv and "/hd:/harness:ro" in argv
    assert f"HTTPS_PROXY=http://harness-door-abc:{DOOR_PORT}" in argv
    assert "-e" in argv and "HI_PROVIDER_KEY" in argv and "HI_PROVIDER_KEY=k" not in argv   # names only; values stay in the client env
    door = sb.door_argv(names, job.egress)
    assert door[:2] == ["run", "-d"] and door[-2:] == ["api.deepseek.com:443", "pypi.org:443"]
    assert "--network" in door and door[door.index("--network") + 1] == "harness-net-abc"
    assert any(x.endswith("egress.py:/door/egress.py:ro") for x in door)
    assert all(flag in door for flag in LOCKDOWN)                          # the door is locked down like the run


def test_hand_over_gives_the_workspace_to_the_sandbox_user(tmp_path):
    import os
    from harness_interface.docker import UID
    if os.geteuid() != 0:
        pytest.skip("only a server running as root changes ownership")
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "f.txt").write_text("x")
    DockerRuntime.hand_over(tmp_path)
    assert {p.stat().st_uid for p in [tmp_path, *tmp_path.rglob("*")]} == {UID}


@pytest.mark.anyio
async def test_the_run_waits_for_the_door(monkeypatch):
    from harness_interface import docker
    logs = iter(["", "", "door listening\n"])
    calls = []

    async def fake_docker(*args, **_):
        calls.append(args)
        return 0, next(logs)
    monkeypatch.setattr(docker, "docker", fake_docker)
    await DockerRuntime.door_ready(DockerNames.of("abc"))
    assert calls == [("logs", "harness-door-abc")] * 3

    async def gone(*args, **_):                   # the door exited: docker logs fails, the run does not start
        return 1, "No such container"
    monkeypatch.setattr(docker, "docker", gone)
    with pytest.raises(RuntimeError, match="egress door did not start"):
        await DockerRuntime.door_ready(DockerNames.of("abc"))


@pytest.fixture
def anyio_backend():
    return "asyncio"
