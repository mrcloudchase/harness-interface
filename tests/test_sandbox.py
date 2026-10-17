"""What the Docker sandbox would run, without a daemon: the image tag, the door, the container."""
from pathlib import Path

from hi.models import Sandbox
from hi.runner import Prepared
from hi.sandbox import DOOR_PORT, HARDENING, DockerNames, DockerSandbox, Job


def test_image_tag_follows_the_dockerfile_content():
    a, b = Sandbox(name="s", dockerfile="FROM a"), Sandbox(name="s", dockerfile="FROM b")
    assert DockerSandbox.tag(a) != DockerSandbox.tag(b) and DockerSandbox.tag(a) == DockerSandbox.tag(Sandbox(name="s", dockerfile="FROM a"))
    assert DockerSandbox.tag(a).startswith("hi/s:")


def test_run_and_door_argv(tmp_path):
    sb = DockerSandbox(tmp_path, tmp_path)
    assert sb.mounts(Path("/x"), Path("/y")).workspace == "/workspace"
    prepared = Prepared(argv=["bash", "/harness/run.sh"], env={"HI_TASK": "t", "HI_PROVIDER_KEY": "k", "HOME": "/workspace/.home"},
                        stdin=b"{}", timeout_s=9)
    job = Job(id="abc", prepared=prepared, workspace=Path("/ws"), harness_dir=Path("/hd"), log_path=tmp_path / "l",
              spec=Sandbox(name="default", dockerfile="FROM x"), egress=["api.deepseek.com:443", "pypi.org:443"])
    names = DockerNames.of("abc")
    argv = sb.run_argv(job, "hi/default:deadbeef", names)
    assert argv[:2] == ["docker", "run"] and argv[-3:] == ["hi/default:deadbeef", "bash", "/harness/run.sh"]
    assert "--network" in argv and argv[argv.index("--network") + 1] == "hi-net-abc"
    assert "--runtime" not in argv
    assert "/tmp:rw,exec,nosuid,nodev,size=512m" in argv                 # native modules load from /tmp
    assert all(flag in argv for flag in HARDENING)
    assert "/ws:/workspace" in argv and "/hd:/harness:ro" in argv
    assert f"HTTPS_PROXY=http://hi-door-abc:{DOOR_PORT}" in argv
    assert "-e" in argv and "HI_PROVIDER_KEY" in argv and "HI_PROVIDER_KEY=k" not in argv   # names only; values stay in the client env
    door = sb.door_argv(names, job.egress)
    assert door[:2] == ["run", "-d"] and door[-2:] == ["api.deepseek.com:443", "pypi.org:443"]
    assert "--network" in door and door[door.index("--network") + 1] == "hi-net-abc"
    assert any(x.endswith("egress.py:/door/egress.py:ro") for x in door)


def test_hand_over_gives_the_workspace_to_the_sandbox_user(tmp_path):
    import os
    import pytest
    from hi.sandbox import UID
    if os.geteuid() != 0:
        pytest.skip("only a server running as root changes ownership")
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "f.txt").write_text("x")
    DockerSandbox.hand_over(tmp_path)
    assert {p.stat().st_uid for p in [tmp_path, *tmp_path.rglob("*")]} == {UID}
