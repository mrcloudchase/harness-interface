"""Layer 1: the local runtime's provider. Under the gateway, a run on this machine calls a gateway on
loopback with the session's token, and only the gateway holds the key; in file mode it reads the key
from its credential file. The URL and the credential's path are the runtime's own, the same for every
run; loopback is never proxied; and the credential and the gateway are gone when the run is."""
import asyncio
import os
import socket
import stat
import sys
from urllib.parse import urlsplit

import pytest

from harness_interface.execution import Spec
from harness_interface.runtimes.docker import Provider, owner_of
from harness_interface.runtimes.local import LocalRuntime
from upstream import FIRST, SECOND, Upstream

KEY, TOKEN = "sk-real-provider-key-" + os.urandom(6).hex(), "sk-ant-api03-hi-" + os.urandom(6).hex()

# Calls the provider the way a harness does: the URL from HI_PROVIDER_URL, the credential from its file.
CALL = r"""
import os, sys, urllib.request, urllib.error
key = open(os.environ["HI_PROVIDER_KEY_FILE"]).read()
print("key-file", key, flush=True)
if len(sys.argv) > 1:
    key = sys.argv[1]
req = urllib.request.Request(os.environ["HI_PROVIDER_URL"] + "/v1/messages", data=b"{}", headers={"x-api-key": key})
try:
    print(urllib.request.urlopen(req, timeout=10).read().decode(), flush=True)
except urllib.error.HTTPError as e:
    print("HTTP", e.code, flush=True)
"""


@pytest.fixture
def upstream(tmp_path):
    up = Upstream(tmp_path)
    yield up
    up.close()


@pytest.fixture(autouse=True)
def secrets(tmp_path, monkeypatch):
    monkeypatch.setattr("harness_interface.runtimes.local.SECRETS", tmp_path / "shm")
    (tmp_path / "shm").mkdir()
    return tmp_path / "shm"


def spec(runtime, *args, env=None) -> Spec:
    return Spec([sys.executable, "-c", CALL, *args], env={"HI_PROVIDER_URL": runtime.provider_url,
                                                           "HI_PROVIDER_KEY_FILE": str(runtime.key_path), **(env or {})})


async def run(runtime, spec):
    execution = await runtime.start(spec)
    out = b"".join([e.data async for e in execution.events() if e.stream == "stdout"]).decode()
    return out, await execution.wait()


def listening(url: str) -> bool:
    u = urlsplit(url)
    try:
        socket.create_connection((u.hostname, u.port), timeout=1).close()
        return True
    except OSError:
        return False


def test_under_the_gateway_the_run_holds_a_token_and_the_provider_gets_the_key(upstream, secrets):
    provider = Provider(upstream.url + "/anthropic", "anthropic-messages", KEY, token=TOKEN)
    rt = LocalRuntime(provider, ca_file=upstream.ca)
    assert rt.provider_url.startswith("http://127.0.0.1:") and rt.provider_url.endswith("/anthropic")
    out, outcome = asyncio.run(run(rt, spec(rt)))
    assert outcome.ok and f"key-file {TOKEN}" in out and KEY not in out
    assert (FIRST + SECOND).decode() in out
    sent = upstream.requests[0].decode("latin-1")
    assert sent.startswith("POST /anthropic/v1/messages ") and f"x-api-key: {KEY}" in sent and TOKEN not in sent
    assert not listening(rt.provider_url) and list(secrets.iterdir()) == []


def test_a_credential_is_named_for_its_runtimes_owner(upstream, secrets, tmp_path):
    owner = owner_of(tmp_path)
    rt = LocalRuntime(Provider(upstream.url, "anthropic-messages", KEY, token=TOKEN), owner=owner)
    assert rt.key_path.parent.parent == secrets and rt.key_path.parent.name.startswith(f"hi-{owner}-")
    assert LocalRuntime().owner != LocalRuntime().owner


def test_the_gateway_refuses_anything_but_the_token(upstream):
    rt = LocalRuntime(Provider(upstream.url, "anthropic-messages", KEY, token=TOKEN), ca_file=upstream.ca)
    out, _ = asyncio.run(run(rt, spec(rt, "sk-guessed")))
    assert "HTTP 401" in out and upstream.requests == []


def test_every_run_of_a_runtime_has_the_same_url_and_credential_path(upstream):
    rt = LocalRuntime(Provider(upstream.url, "anthropic-messages", KEY, token=TOKEN), ca_file=upstream.ca)
    first = (rt.provider_url, rt.key_path)
    for _ in range(2):
        out, outcome = asyncio.run(run(rt, spec(rt)))
        assert outcome.ok and (FIRST + SECOND).decode() in out
    assert (rt.provider_url, rt.key_path) == first and len(upstream.requests) == 2


def test_in_file_mode_the_run_reads_the_key_and_calls_the_provider_itself(upstream, secrets):
    rt = LocalRuntime(Provider(upstream.url, "anthropic-messages", KEY, credential="file"))
    assert rt.provider_url == upstream.url

    async def go():
        execution = await rt.start(Spec([sys.executable, "-c", "import os, sys; p = os.environ['F'];"
                                         "print(oct(os.stat(p).st_mode & 0o777), open(p).read())"],
                                        env={"F": str(rt.key_path)}))
        out = b"".join([e.data async for e in execution.events() if e.stream == "stdout"]).decode()
        return out, await execution.wait()
    out, outcome = asyncio.run(go())
    assert outcome.ok and out.split() == [oct(stat.S_IRUSR), KEY]
    assert list(secrets.iterdir()) == []


def test_loopback_is_never_proxied(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "internal.example")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    out, _ = asyncio.run(run(LocalRuntime(), Spec([sys.executable, "-c", "import os; print(os.environ['NO_PROXY'])"])))
    assert set(out.strip().split(",")) == {"internal.example", "127.0.0.1", "localhost"}


def test_a_cancelled_start_leaves_no_gateway_and_no_credential(upstream, secrets):
    rt = LocalRuntime(Provider(upstream.url, "anthropic-messages", KEY, token=TOKEN), ca_file=upstream.ca)

    async def go():
        task = asyncio.ensure_future(rt.start(Spec([sys.executable, "-c", "import time; time.sleep(30)"])))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(go())
    assert not listening(rt.provider_url) and list(secrets.iterdir()) == []


def test_a_run_that_cannot_start_leaves_nothing_either(upstream, secrets):
    rt = LocalRuntime(Provider(upstream.url, "anthropic-messages", KEY, token=TOKEN), ca_file=upstream.ca)
    _, outcome = asyncio.run(run(rt, Spec(["/no/such/program"])))
    assert outcome.kind == "failed" and not listening(rt.provider_url) and list(secrets.iterdir()) == []
