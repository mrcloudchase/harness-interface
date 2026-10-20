"""Layer 1, against a real Docker daemon: what the Docker runtime promises holds inside running
containers. A stop reaches a process `bash run.sh` started; a run reaches only what it is given, with
no DNS; the gateway forwards with the real key and refuses anything else; the key is nowhere but the
door; and nothing is left after any ending. Run with `pytest -m docker`; CI runs it on every pull
request. The stand-in provider listens on this host's Docker bridge, which only the door can reach."""
import asyncio
import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from harness_interface.execution import Outcome, Spec
from harness_interface.runtimes.docker import KEY_PATH, SECRETS, DockerRuntime, Images, Provider
from upstream import FIRST, SECOND, Upstream

pytestmark = pytest.mark.docker

DOCKERFILE = "FROM python:3.12-slim\nUSER 1000:1000\n"            # bash and python, and nothing of ours
KEY, TOKEN = "sk-live-test-key-" + os.urandom(8).hex(), "sk-ant-api03-hi-" + os.urandom(8).hex()


def docker_ok() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


@pytest.fixture(autouse=True)
def needs_docker():
    if not docker_ok():
        pytest.skip("no Docker daemon")
    yield
    assert leftovers() == []                         # every test, whatever its ending, leaves nothing


@pytest.fixture(scope="module")
def image(tmp_path_factory):
    return asyncio.run(Images(tmp_path_factory.mktemp("logs")).ensure("live-test", DOCKERFILE))


@pytest.fixture(scope="module")
def bridge() -> str:
    """This host's address on Docker's bridge: reachable from the door, never from a run."""
    return subprocess.run(["docker", "network", "inspect", "bridge", "-f", "{{(index .IPAM.Config 0).Gateway}}"],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def echo(bridge):
    """A TCP server on the bridge that says hello: a host a run may be allowed to reach."""
    server = socket.create_server((bridge, 0))

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            conn.sendall(b"hello")
            conn.close()
    threading.Thread(target=serve, daemon=True).start()
    yield f"{bridge}:{server.getsockname()[1]}"
    server.close()


@pytest.fixture
def upstream(bridge, tmp_path):
    up = Upstream(tmp_path, ip=bridge, bind=bridge)
    yield up
    up.close()


def leftovers() -> list[str]:
    ps = subprocess.run(["docker", "ps", "-aq", "--filter", "name=^hi-run-", "--filter", "name=^hi-door-"],
                        capture_output=True, text=True).stdout
    nets = subprocess.run(["docker", "network", "ls", "-q", "--filter", "name=^hi-net-"],
                          capture_output=True, text=True).stdout
    return ps.split() + nets.split() + [str(p) for p in SECRETS.glob("hi-" + "[0-9a-f]" * 12)]


def run(runtime, spec) -> tuple[str, Outcome]:
    """Start it, and its stdout and outcome."""
    async def go():
        execution = await runtime.start(spec)
        out = b"".join([e.data async for e in execution.events() if e.stream == "stdout"])
        return out.decode(), await execution.wait()
    return asyncio.run(go())


PROBE = r"""
import json, os, socket, sys
def connect(target):
    host, port = os.environ["HTTPS_PROXY"].removeprefix("http://").rsplit(":", 1)
    s = socket.create_connection((host, int(port)), timeout=10)
    s.sendall(f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
    data = b""
    while b"\r\n\r\n" not in data and (chunk := s.recv(64)):        # the reply and the tunnel's first bytes may share a read
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode()
    if not status.endswith("200 Connection established"):
        return status
    while len(body) < len(b"hello") and (chunk := s.recv(64)):
        body += chunk
    return status + " " + body.decode()
def direct(target):
    host, port = target.rsplit(":", 1)
    try:
        socket.create_connection((host, int(port)), timeout=3); return "reached"
    except OSError:
        return "unreachable"
def resolves(name):
    try:
        socket.getaddrinfo(name, 443); return True
    except OSError:
        return False
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
    "read_only_writable": writes(os.environ["READ_ONLY"] + "/x"),
    "writable_writable": writes(os.environ["WRITABLE"] + "/x"),
    "allowed": connect(os.environ["ALLOWED"]),
    "refused": connect("example.com:443"),
    "direct": direct(os.environ["ALLOWED"]),
    "dns": resolves("example.com"),
    "key": open(os.environ["KEY_FILE"]).read() if os.environ.get("KEY_FILE") else None,
}))
"""


def test_inside_a_run_it_is_locked_down_and_reaches_only_what_it_is_given(image, echo, tmp_path):
    ws, read_only, writable = tmp_path / "ws", tmp_path / "tools", tmp_path / "rundir"
    for d in (ws, read_only, writable):
        d.mkdir()
    rt = DockerRuntime(image, read_only=[read_only], writable=[writable], egress=[echo])
    env = {"READ_ONLY": str(read_only), "WRITABLE": str(writable), "ALLOWED": echo}
    out, outcome = run(rt, Spec(["python3", "-c", PROBE], env=env, workspace=ws, timeout_s=120))
    assert outcome.ok, out
    seen = json.loads(out)
    assert seen["uid"] == (1000 if os.geteuid() == 0 else os.getuid()) and seen["caps"] == "0000000000000000"
    assert not seen["root_writable"] and seen["workspace_writable"] and (ws / "made-inside").exists()
    assert not seen["read_only_writable"] and seen["writable_writable"] and (writable / "x").exists()
    assert seen["allowed"] == "HTTP/1.1 200 Connection established hello" and seen["refused"].startswith("HTTP/1.1 403")
    assert seen["direct"] == "unreachable" and not seen["dns"]          # no way round the door, no names of its own


def test_in_file_mode_the_run_reads_the_key_and_reaches_its_provider(image, echo, tmp_path):
    provider = Provider(f"https://{echo}", "openai-chat", KEY, credential="file")
    rt = DockerRuntime(image, provider=provider)
    env = {"READ_ONLY": "/usr", "WRITABLE": "/tmp", "ALLOWED": echo, "KEY_FILE": str(KEY_PATH)}
    out, outcome = run(rt, Spec(["python3", "-c", PROBE], env=env, workspace=tmp_path, timeout_s=120))
    seen = json.loads(out)
    assert outcome.ok and seen["key"] == KEY and seen["allowed"].endswith("hello")


RUN_SH = """\
python3 - <<'EOF'
import os, signal, sys, time
signal.signal(signal.SIGINT, lambda *_: (os.write(1, b"child got SIGINT\\n"), sys.exit(0)))
print("ready", flush=True)
time.sleep(60)
EOF
echo "run.sh went on"
"""


def test_a_stop_reaches_a_process_run_sh_started_through_tini(image, tmp_path):
    (tmp_path / "run.sh").write_text(RUN_SH)

    async def go():
        e = await DockerRuntime(image).start(Spec(["bash", str(tmp_path / "run.sh")], workspace=tmp_path))
        events, out = e.events(), b""
        while b"ready" not in out:
            out += (await events.__anext__()).data
        e.stop(30)
        out += b"".join([ev.data async for ev in events if ev.stream == "stdout"])
        return out.decode(), await e.wait()
    out, outcome = asyncio.run(go())
    assert "child got SIGINT" in out and "run.sh went on" in out and outcome == Outcome.stopped(0)


GATEWAY_PROBE = r"""
import http.client, json, os, sys
from urllib.parse import urlsplit
u = urlsplit(os.environ["PROVIDER_URL"])
token = open(os.environ["KEY_FILE"]).read()
def post(key):
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=30)
    c.request("POST", u.path + "/v1/messages", body=b'{"stream": true}', headers={"x-api-key": key})
    r = c.getresponse()
    return r.status, r.read().decode()
mine = []
for pid in os.listdir("/proc"):
    if pid.isdigit():
        for what in ("environ", "cmdline"):
            try:
                mine.append(open(f"/proc/{pid}/{what}", "rb").read().decode(errors="replace"))
            except OSError:
                pass
print(json.dumps({"token": token, "ok": post(token), "wrong": post("sk-ant-api03-hi-guess"), "procs": mine}),
      flush=True)
sys.stdin.readline()                                 # stay up while the host is searched
"""


def test_under_the_gateway_the_key_reaches_the_provider_and_nothing_else(image, upstream, tmp_path):
    provider = Provider(upstream.url, "anthropic-messages", KEY, token=TOKEN)
    rt = DockerRuntime(image, provider=provider, ca_file=upstream.ca)
    env = {"PROVIDER_URL": rt.provider_url, "KEY_FILE": str(KEY_PATH)}

    async def go():
        e = await rt.start(Spec(["python3", "-c", GATEWAY_PROBE], env=env, workspace=tmp_path, interactive=True,
                                timeout_s=120))
        events, out = e.events(), b""
        while b"\n" not in out:
            out += next_stdout(await events.__anext__())
        found = await asyncio.to_thread(search_the_host)
        await e.end_input()
        async for _ in events:
            pass
        return json.loads(out), found, await e.wait()
    seen, found, outcome = asyncio.run(go())
    assert outcome.ok and rt.provider_url == "http://hi-provider:8080"
    assert seen["token"] == TOKEN and seen["ok"] == [200, (FIRST + SECOND).decode()] and seen["wrong"][0] == 401
    [request] = upstream.requests                    # the wrong token never left the door
    assert f"x-api-key: {KEY}".encode() in request and TOKEN.encode() not in request
    assert not any(KEY in p for p in seen["procs"])  # not in any environment or command line inside
    assert found == []


def next_stdout(event) -> bytes:
    return event.data if event.stream == "stdout" else b""


def search_the_host() -> list[str]:
    """Everywhere the key must never be, on this host, while the run is up."""
    names = subprocess.run(["docker", "ps", "-q", "--filter", "name=^hi-"], capture_output=True, text=True).stdout
    found = []
    inspect = subprocess.run(["docker", "inspect", *names.split()], capture_output=True, text=True).stdout
    if KEY in inspect:
        found.append("docker inspect")
    assert len(json.loads(inspect)) == 2             # the run and its door
    for proc in Path("/proc").glob("[0-9]*"):
        for what in ("cmdline", "environ"):
            try:
                if KEY.encode() in (proc / what).read_bytes():
                    found.append(f"{proc}/{what}")
            except OSError:
                pass
    return found


@pytest.mark.parametrize("ending", ["stop", "kill", "timeout"])
def test_nothing_is_left_after_any_ending(image, tmp_path, ending):
    provider = Provider("https://api.example.com", "openai-chat", KEY, token=TOKEN)

    async def go():
        spec = Spec(["sleep", "60"], workspace=tmp_path, timeout_s=2 if ending == "timeout" else None)
        e = await DockerRuntime(image, provider=provider).start(spec)
        if ending == "stop":
            e.stop(10)
        elif ending == "kill":
            e.kill()
        return await e.wait()
    assert asyncio.run(go()).kind == {"stop": "stopped", "kill": "killed", "timeout": "timed_out"}[ending]


def test_a_start_cancelled_during_setup_leaves_nothing(image, tmp_path):
    provider = Provider("https://api.example.com", "openai-chat", KEY, token=TOKEN)

    async def go():
        task = asyncio.create_task(DockerRuntime(image, provider=provider).start(Spec(["sleep", "60"])))
        while not subprocess.run(["docker", "ps", "-q", "--filter", "name=^hi-door-"], capture_output=True,
                                 text=True).stdout.strip():
            await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
