"""Layer 1, against a real Docker daemon: what the Docker runtime promises holds inside a running
container. Run with `pytest -m docker`; CI runs it on every pull request."""
import asyncio
import json
import subprocess

import pytest

from harness_interface.execution import Outcome, Spec
from harness_interface.runtimes import Docker, DockerRuntime, Sandbox
from harness_interface.runtimes.docker import PREFIX

pytestmark = pytest.mark.docker

BOX = Sandbox("hi-test", "FROM python:3.12-alpine\nRUN adduser -D -u 1000 runner\nUSER runner\n")

PROBE = r"""
import json, os, socket
def connect(host):
    proxy = os.environ["HTTPS_PROXY"].removeprefix("http://")
    h, p = proxy.rsplit(":", 1)
    s = socket.create_connection((h, int(p)), timeout=10)
    s.sendall(f"CONNECT {host} HTTP/1.1\r\n\r\n".encode())
    return s.recv(64).split(b"\r\n")[0].decode()
def writes(path):
    try:
        open(path, "w").write("x"); return True
    except OSError:
        return False
status = open("/proc/self/status").read()
print(json.dumps({
    "uid": os.getuid(),
    "caps": [l.split()[1] for l in status.splitlines() if l.startswith("CapEff")][0],
    "root_writable": writes("/root-file"),
    "workspace_writable": writes(os.path.join(os.getcwd(), "made-inside")),
    "mount_writable": writes(os.environ["MOUNT"] + "/x"),
    "allowed": connect("example.com:443"),
    "refused": connect("example.org:443"),
}))
"""


def docker_ok() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


@pytest.fixture(autouse=True)
def needs_docker():
    if not docker_ok():
        pytest.skip("no Docker daemon")


def leftovers() -> list[str]:
    ps = subprocess.run(["docker", "ps", "-aq", "--filter", f"name={PREFIX}"], capture_output=True, text=True).stdout
    nets = subprocess.run(["docker", "network", "ls", "-q", "--filter", f"name={PREFIX}net-"], capture_output=True, text=True).stdout
    return ps.split() + nets.split()


def test_inside_a_run_the_promises_hold(tmp_path):
    ws, mount = tmp_path / "ws", tmp_path / "scripts"
    ws.mkdir()
    mount.mkdir()
    runtime = DockerRuntime(Docker(tmp_path / "logs"), BOX, egress=["example.com"], mounts=[mount])

    async def go():
        e = await runtime.start(Spec(["python3", "-c", PROBE], env={"MOUNT": str(mount)}, workspace=ws, timeout_s=120))
        out = b"".join([ev.data async for ev in e.events() if ev.stream == "stdout"])
        return out, await e.wait()
    out, outcome = asyncio.run(go())
    assert outcome.ok, out
    seen = json.loads(out)
    assert seen["uid"] == 1000 and seen["caps"] == "0000000000000000"
    assert not seen["root_writable"] and seen["workspace_writable"] and not seen["mount_writable"]
    assert (ws / "made-inside").exists()                               # the workspace is the same directory
    assert seen["allowed"].startswith("HTTP/1.1 200") and seen["refused"].startswith("HTTP/1.1 403")
    assert leftovers() == []


def test_a_cancelled_run_leaves_nothing(tmp_path):
    runtime = DockerRuntime(Docker(tmp_path / "logs"), BOX)

    async def go():
        e = await runtime.start(Spec(["sleep", "60"]))
        e.cancel()
        return await e.wait()
    assert asyncio.run(go()) == Outcome.cancelled()
    assert leftovers() == []
