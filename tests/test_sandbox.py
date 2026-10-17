"""What the Docker sandbox would run, without a daemon: the image tag, the door, the container."""
from pathlib import Path

from hi.models import Sandbox
from hi.runner import Prepared
from hi.sandbox import DOOR_PORT, HARDENING, DockerNames, DockerSandbox, Job


def test_image_tag_follows_the_rendered_dockerfile():
    a, b = Sandbox(name="s", dockerfile="FROM a"), Sandbox(name="s", dockerfile="FROM b")
    assert DockerSandbox.tag(a, "x") != DockerSandbox.tag(b, "x") and DockerSandbox.tag(a, "x") == DockerSandbox.tag(Sandbox(name="s", dockerfile="FROM a"), "x")
    assert DockerSandbox.tag(a, "x").startswith("hi/s:")
    assert DockerSandbox.tag(a, "codex") == DockerSandbox.tag(a, "claude-code")          # no {harness}: one image for all
    named = Sandbox(name="s", dockerfile="FROM a\nRUN useradd {harness}\nUSER {harness}\nENV X=${HOME}")
    assert DockerSandbox.tag(named, "codex") != DockerSandbox.tag(named, "claude-code")  # {harness}: one image each
    assert DockerSandbox.dockerfile(named, "codex") == "FROM a\nRUN useradd codex\nUSER codex\nENV X=${HOME}"


def test_run_and_door_argv(tmp_path):
    sb = DockerSandbox(tmp_path, tmp_path)
    assert sb.mounts(Path("/x"), Path("/y")).workspace == "/workspace"
    prepared = Prepared(argv=["bash", "/harness/run.sh"], env={"HI_TASK": "t", "HI_PROVIDER_KEY": "k", "HOME": "/workspace/.home"},
                        stdin=b"{}", timeout_s=9)
    job = Job(id="abc", harness="claude-code", prepared=prepared, workspace=Path("/ws"), harness_dir=Path("/hd"), log_path=tmp_path / "l",
              spec=Sandbox(name="default", dockerfile="FROM x"), egress=["api.deepseek.com:443", "pypi.org:443"])
    names = DockerNames.of("abc")
    argv = sb.run_argv(job, "hi/default:deadbeef", "runsc", names, "172.30.0.2")
    assert argv[:2] == ["docker", "run"] and argv[-3:] == ["hi/default:deadbeef", "bash", "/harness/run.sh"]
    assert "--network" in argv and argv[argv.index("--network") + 1] == "hi-net-abc"
    assert argv[argv.index("--runtime") + 1] == "runsc" and argv[argv.index("--hostname") + 1] == "claude-code"
    assert all(flag in argv for flag in HARDENING)
    assert "/ws:/workspace" in argv and "/hd:/harness:ro" in argv
    assert f"HTTPS_PROXY=http://172.30.0.2:{DOOR_PORT}" in argv           # the door by address: no DNS under gVisor
    assert "-e" in argv and "HI_PROVIDER_KEY" in argv and "HI_PROVIDER_KEY=k" not in argv   # names only; values stay in the client env
    door = sb.door_argv(names, job.egress)
    assert door[:2] == ["run", "-d"] and door[-2:] == ["api.deepseek.com:443", "pypi.org:443"]
    assert "--network" in door and door[door.index("--network") + 1] == "hi-net-abc"
    assert any(x.endswith("egress.py:/door/egress.py:ro") for x in door)
