"""Layer 1: the door tunnels only to the hosts it is given, and its gateway forwards only requests
that present the session's token, with the real key in the header the API shape uses, never letting
an upstream failure corrupt a response already under way. The key reaches it on stdin only."""
import asyncio
import os
import ssl
import subprocess
import sys
from pathlib import Path

import pytest

from harness_interface.runtimes import door
from harness_interface.runtimes.door import READY, Door, Gateway, normalize
from upstream import FIRST, SECOND, Upstream

TOKEN, KEY = "sk-hi-session-token", "sk-real-key-never-in-the-sandbox"


def test_normalize():
    assert normalize("api.deepseek.com") == "api.deepseek.com:443"
    assert normalize("https://api.deepseek.com/anthropic") == "api.deepseek.com:443"
    assert normalize("http://localhost:8080/v1") == "localhost:8080"
    assert normalize("Host.Example:8443") == "host.example:8443"


async def _exchange(port: int, data: bytes, then: bytes = b"") -> bytes:
    """Send `data`; on a 200, send `then`; read to the end."""
    r, w = await asyncio.open_connection("127.0.0.1", port)
    w.write(data)
    await w.drain()
    got = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), timeout=5)
    if got.startswith(b"HTTP/1.1 200") and then:
        w.write(then)
        await w.drain()
    while chunk := await asyncio.wait_for(r.read(4096), timeout=5):
        got += chunk
    w.close()
    return got


# ── the CONNECT door ───────────────────────────────────────────────────────────────────────────
def test_the_door_tunnels_the_allowed_and_refuses_the_rest(capsys):
    async def go():
        async def upstream(reader, writer):          # a plain TCP echo, standing in for a provider
            writer.write(b"upstream saw " + await reader.read(100))
            await writer.drain()
            writer.close()
        up = await asyncio.start_server(upstream, "127.0.0.1", 0)
        up_port = up.sockets[0].getsockname()[1]
        server = await asyncio.start_server(Door([f"127.0.0.1:{up_port}", "127.0.0.1:1"]).handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        async with up, server:
            ok = await _exchange(port, f"CONNECT 127.0.0.1:{up_port} HTTP/1.1\r\n\r\n".encode(), b"\x00\xffhello")
            assert ok.startswith(b"HTTP/1.1 200") and ok.endswith(b"upstream saw \x00\xffhello")   # bytes untouched
            for head in (b"CONNECT 127.0.0.1:9 HTTP/1.1\r\n\r\n",                  # another port
                         b"CONNECT example.com:443 HTTP/1.1\r\n\r\n",              # another host
                         b"GET http://127.0.0.1:%d/?key=sk-x HTTP/1.1\r\n\r\n" % up_port,   # not a tunnel
                         b"GET / HTTP/1.1\r\nHost: door\r\n\r\n"):                # the door itself
                assert (await _exchange(port, head)).startswith(b"HTTP/1.1 403")
            assert (await _exchange(port, b"CONNECT 127.0.0.1:1 HTTP/1.1\r\n\r\n")).startswith(b"HTTP/1.1 502")
    asyncio.run(go())
    log = capsys.readouterr().err
    assert "door deny example.com:443" in log and "door allow 127.0.0.1:" in log
    assert "sk-x" not in log                         # a refused request's URL is never logged


# ── the provider gateway ───────────────────────────────────────────────────────────────────────
@pytest.fixture
def upstream(tmp_path):
    up = Upstream(tmp_path)
    yield up
    up.close()


def gateway(up: Upstream, api: str = "anthropic-messages") -> Gateway:
    return Gateway(up.url, api, TOKEN, KEY, tls=ssl.create_default_context(cafile=up.ca))


async def through(gw: Gateway, request: bytes) -> bytes:
    server = await asyncio.start_server(gw.handle, "127.0.0.1", 0)
    async with server:
        return await _exchange(server.sockets[0].getsockname()[1], request)


def post(auth: str, path: str = "/anthropic/v1/messages?beta=true", body: bytes = b'{"stream": true}') -> bytes:
    return (f"POST {path} HTTP/1.1\r\nHost: hi-provider:8080\r\n{auth}Content-Type: application/json\r\n"
            f"Connection: keep-alive\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body


@pytest.mark.parametrize("api, presented, expected", [
    ("anthropic-messages", f"x-api-key: {TOKEN}\r\n", f"x-api-key: {KEY}"),
    ("openai-responses", f"Authorization: Bearer {TOKEN}\r\n", f"authorization: Bearer {KEY}"),
    ("openai-chat", f"Authorization: Bearer {TOKEN}\r\napi-key: {TOKEN}\r\n", f"authorization: Bearer {KEY}"),
])
def test_the_gateway_swaps_the_token_for_the_key_the_shape_uses(upstream, api, presented, expected):
    got = asyncio.run(through(gateway(upstream, api), post(presented)))
    assert got.startswith(b"HTTP/1.1 200") and got.endswith(FIRST + SECOND) and b"Connection: close" in got
    [seen] = upstream.requests
    head, body = seen.decode().split("\r\n\r\n", 1)
    lines = [line.lower() if line.lower().startswith(("authorization", "x-api-key")) else line
             for line in head.split("\r\n")]
    assert lines[0] == "POST /anthropic/v1/messages?beta=true HTTP/1.1" and body == '{"stream": true}'
    assert f"Host: 127.0.0.1:{upstream.port}" in lines and "Content-Type: application/json" in lines
    assert expected.lower() in lines and sum(line.startswith(("authorization", "x-api-key", "api-key"))
                                             for line in lines) == 1
    assert TOKEN not in seen.decode()                # the token never leaves the session's network


@pytest.mark.parametrize("presented", [
    "",                                              # no credential
    "x-api-key: sk-hi-another-session\r\n",          # someone else's token
    f"x-api-key: {KEY}\r\n",                         # even the real key: only the token gets in
    f"x-api-key: {TOKEN}\r\nAuthorization: Bearer other\r\n",   # the token, and something else besides
])
def test_the_gateway_refuses_anything_but_the_token(upstream, presented, capsys):
    got = asyncio.run(through(gateway(upstream), post(presented)))
    assert got.startswith(b"HTTP/1.1 401") and upstream.requests == []
    log = capsys.readouterr().err
    assert "gateway refuse POST /anthropic/v1/messages" in log and "beta" not in log and KEY not in log


class Recorder:
    """A client's side of the connection that keeps every byte written to it, even after a close, so
    nothing the gateway writes too late can hide. It tells the upstream when the first event is in."""

    def __init__(self, upstream: Upstream):
        self.data, self.closed, self.upstream = b"", False, upstream

    def write(self, data: bytes) -> None:
        self.data += data
        if FIRST in self.data:
            self.upstream.first_seen.set()

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_an_upstream_failure_after_the_head_only_closes_the_response(upstream, capsys):
    upstream.breaks = True
    client = Recorder(upstream)

    async def go():
        request = asyncio.StreamReader()
        request.feed_data(post(f"x-api-key: {TOKEN}\r\n"))   # and the client waits for its answer
        await asyncio.wait_for(gateway(upstream).handle(request, client), 10)
    asyncio.run(go())
    assert client.data.startswith(b"HTTP/1.1 200") and client.data.endswith(FIRST) and client.closed
    assert b"502" not in client.data and "gateway error SSLError" in capsys.readouterr().err


def test_an_unreachable_upstream_is_a_bad_gateway():
    gw = Gateway("https://127.0.0.1:1", "openai-chat", TOKEN, KEY)
    assert asyncio.run(through(gw, post(f"Authorization: Bearer {TOKEN}\r\n"))).startswith(b"HTTP/1.1 502")


@pytest.mark.parametrize("upstream_url, api", [("http://api.example.com", "openai-chat"),
                                               ("https://api.example.com", "openai-websocket")])
def test_the_gateway_only_speaks_tls_to_a_known_shape(upstream_url, api):
    with pytest.raises(ValueError):
        Gateway(upstream_url, api, TOKEN, KEY)


def test_a_gateway_is_never_shown_with_its_key(upstream):
    assert KEY not in repr(gateway(upstream)) and TOKEN not in repr(gateway(upstream))


# ── the door as a program, as its container runs it ────────────────────────────────────────────
def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_program_takes_its_key_on_stdin_only(upstream, tmp_path):
    door_port, gateway_port = free_port(), free_port()
    env = {"PATH": os.environ["PATH"], "SSL_CERT_FILE": str(upstream.ca)}
    proc = subprocess.Popen([sys.executable, door.__file__, f"127.0.0.1:{door_port}", "--gateway",
                             f"127.0.0.1:{gateway_port}", upstream.url, "anthropic-messages"],
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=tmp_path)
    try:
        proc.stdin.write(f"{TOKEN}\n{KEY}\n".encode())
        proc.stdin.close()
        assert proc.stderr.readline().decode().strip() == READY
        for where in ("cmdline", "environ"):
            assert KEY.encode() not in Path(f"/proc/{proc.pid}/{where}").read_bytes()
        got = asyncio.run(_exchange(gateway_port, post(f"x-api-key: {TOKEN}\r\n")))
        assert got.startswith(b"HTTP/1.1 200") and f"x-api-key: {KEY}".encode() in upstream.requests[0]
    finally:
        proc.kill()
        proc.wait()


def test_the_program_will_not_run_a_gateway_without_a_token_and_a_key(tmp_path):
    proc = subprocess.run([sys.executable, door.__file__, "127.0.0.1:0", "--gateway", "127.0.0.1:0",
                           "https://api.example.com", "openai-chat"], input=b"only-a-token\n", capture_output=True,
                          timeout=10)
    assert proc.returncode != 0 and READY.encode() not in proc.stderr

