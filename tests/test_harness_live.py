"""Layer 3, against a real Docker daemon, with the template's stand-in: the base image builds, the
template installs once into its tools directory through a door that reaches only its install hosts,
and a response in the hardened sandbox is steered, stopped by SIGINT through tini, resumed in a fresh
container, and reaches its provider through the gateway holding only a token. Nothing is left after
any of it. Run with `pytest -m docker`."""
import asyncio
import json
import os
import subprocess
from pathlib import Path

import pytest

from harness_interface.harness.contract import Request, session_token
from harness_interface.harness.folder import HarnessFolder
from harness_interface.harness.install import Installer
from harness_interface.harness.placement import Placement
from harness_interface.harness.response import Response
from harness_interface.runtimes.docker import Images, Provider
from harness_interface.workspace import Workspace
from standin import TEMPLATE, events, variant
from test_docker_live import OWNER, docker_ok, leftovers
from upstream import Upstream

pytestmark = pytest.mark.docker

MACHINE_CA = Path("/root/.ccr/ca-bundle.crt")         # where this machine's network re-signs TLS
CA = MACHINE_CA if MACHINE_CA.is_file() else None
KEY = "sk-live-harness-key-" + os.urandom(8).hex()

# Asks the door for two tunnels and tries DNS, then installs as the template does.
PROBE = r"""
python3 - <<'EOF' > "$HI_TOOLS/probe.json"
import json, os, socket
def connect(target):
    host, port = os.environ["HTTPS_PROXY"].removeprefix("http://").rsplit(":", 1)
    s = socket.create_connection((host, int(port)), timeout=10)
    s.sendall(f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
    return s.recv(64).split(b"\r\n")[0].decode()
def resolves(name):
    try:
        socket.getaddrinfo(name, 443); return True
    except OSError:
        return False
print(json.dumps({"allowed": connect("registry.npmjs.org:443"), "refused": connect("pypi.org:443"),
                  "dns": resolves("pypi.org"), "env": sorted(os.environ)}))
EOF
"""


@pytest.fixture(autouse=True)
def needs_docker():
    if not docker_ok():
        pytest.skip("no Docker daemon")
    yield
    assert leftovers() == []


@pytest.fixture(scope="module")
def placement(tmp_path_factory):
    return Placement(Images(tmp_path_factory.mktemp("logs")), ca_file=CA, owner=OWNER)


@pytest.fixture(scope="module")
def installed(placement, tmp_path_factory):
    """The template, installed once for the module: a miss, then a hit."""
    if not docker_ok():
        pytest.skip("no Docker daemon")
    installer, folder = Installer(tmp_path_factory.mktemp("tools"), placement), HarnessFolder.load(TEMPLATE)
    first = asyncio.run(installer.ensure(folder))
    second = asyncio.run(installer.ensure(folder))
    return first, second


def test_the_template_installs_once_in_the_sandbox_and_then_is_a_hit(installed):
    first, second = installed
    assert not first.cached and second.cached and second.path == first.path
    assert (first.path / "bin" / "semver").exists() and (first.path / "bin" / "standin").is_file()
    assert "door allow registry.npmjs.org:443" in first.log.read_text()


def test_an_install_reaches_only_its_install_hosts_and_holds_no_secret(placement, tmp_path, monkeypatch):
    monkeypatch.setenv("EXT_ANTHROPIC_API_KEY", "sk-from-the-host")
    folder = variant(tmp_path / "probe", install__sh=(TEMPLATE / "install.sh").read_text() + PROBE)
    done = asyncio.run(Installer(tmp_path / "tools", placement).ensure(folder))
    probe = json.loads((done.path / "probe.json").read_text())
    assert probe["allowed"].endswith("200 Connection established") and probe["refused"].endswith("403 Forbidden")
    assert probe["dns"] is False and not any(n.startswith("HI_PROVIDER") or n.endswith("_API_KEY") for n in probe["env"])
    assert "door deny pypi.org:443" in done.log.read_text()


def respond(installed, placement, ws, rundir, request, on=None, **kw):
    """One sandboxed response: its stdout events and its Result; `on(response, seen)` on each event."""
    async def go():
        r = await Response.start(HarnessFolder.load(TEMPLATE), installed[1], ws, request, placement=placement,
                                 rundir=rundir, **kw)
        out = b""
        async for event in r.events():
            if event.stream == "stdout":
                out += event.data
                if on:
                    await on(r, events(out))
        return events(out), await r.result()
    return asyncio.run(go())


def test_a_sandboxed_response_is_steered_stopped_through_tini_and_resumed(installed, placement, tmp_path):
    ws = Workspace(tmp_path / "s" / "workspace")

    async def on(r, seen):
        n = max([e["n"] for e in seen if e["type"] == "count"], default=0)
        if n == 1 and not r.steers_sent:
            await r.steer("count to 60")
        if n == 3 and not r.stopping:
            r.stop()
    seen, first = respond(installed, placement, ws, tmp_path / "run-1", Request("count to 50"), on)
    assert {"type": "hi.stop", "why": "SIGINT"} in seen and any(e["type"] == "steer_accepted" for e in seen)
    assert (first.status, first.outcome.kind, first.steers) == ("stopped", "stopped", 1) and first.resume
    seen, second = respond(installed, placement, ws, tmp_path / "run-2", Request("count to 5", resume=first.resume))
    assert next(e for e in seen if e["type"] == "session")["resumed"]
    assert (second.status, second.answer) == ("ok", "Counted to 5.")
    assert next(e for e in seen if e["type"] == "tools")["semver"] == "1.3.0"   # the cached install, read-only


@pytest.fixture
def bridge() -> str:
    return subprocess.run(["docker", "network", "inspect", "bridge", "-f", "{{(index .IPAM.Config 0).Gateway}}"],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_under_the_gateway_the_sandbox_reaches_its_provider_with_only_a_token(installed, placement, tmp_path, bridge):
    up = Upstream(tmp_path, ip=bridge, bind=bridge)
    provider = Provider(up.url + "/anthropic", "anthropic-messages", KEY, token=session_token("anthropic-messages"))
    ws = Workspace(tmp_path / "s" / "workspace")
    try:
        here = Placement(placement.images, ca_file=up.ca, owner=OWNER)
        seen, result = respond(installed, here, ws, tmp_path / "run-1", Request("count to 1"), provider=provider)
    finally:
        up.close()
    assert {"type": "provider", "status": 200} in seen and result.status == "ok"
    assert f"x-api-key: {KEY}" in up.requests[0].decode("latin-1")
    for root in (tmp_path / "s", tmp_path / "run-1", installed[1].path):
        for p in root.rglob("*"):
            assert not p.is_file() or KEY.encode() not in p.read_bytes(), p


def test_a_harness_brings_os_packages_in_its_own_image_built_from_the_base(placement, tmp_path):
    dockerfile = ("FROM hi-base\nUSER root\nRUN apt-get update && apt-get install -y --no-install-recommends jq"
                  " && rm -rf /var/lib/apt/lists/*\nUSER 1000:1000\n")
    install = (TEMPLATE / "install.sh").read_text() + 'jq --version > "$HI_TOOLS/jq-version"\n'
    folder = variant(tmp_path / "with-jq", image__Dockerfile=dockerfile, install__sh=install)
    done = asyncio.run(Installer(tmp_path / "tools", placement).ensure(folder))
    assert done.image.startswith("hi-harness-template:") and (done.path / "jq-version").read_text().startswith("jq-")
