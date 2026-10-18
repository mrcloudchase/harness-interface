"""The door: a tunnel to an allowlisted host, a refusal for everything else."""
import asyncio

import pytest

from harness_interface.egress import Door, normalize


def test_normalize():
    assert normalize("api.deepseek.com") == "api.deepseek.com:443"
    assert normalize("https://api.deepseek.com/anthropic") == "api.deepseek.com:443"
    assert normalize("http://localhost:8080/v1") == "localhost:8080"
    assert normalize("Host.Example:8443") == "host.example:8443"


async def _request(port: int, head: bytes, then: bytes = b"") -> bytes:
    """Send the request head; on a 200, send `then` through the tunnel and return what comes back."""
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


@pytest.mark.anyio
async def test_door_tunnels_allowed_and_refuses_the_rest():
    async def upstream(reader, writer):           # a plain TCP echo, standing in for a provider
        data = await reader.read(100)
        writer.write(b"upstream saw " + data)
        await writer.drain()
        writer.close()
    up = await asyncio.start_server(upstream, "127.0.0.1", 0)
    up_port = up.sockets[0].getsockname()[1]
    door = await Door([f"127.0.0.1:{up_port}"]).serve("127.0.0.1", 0)
    port = door.sockets[0].getsockname()[1]
    async with up, door:
        ok = await _request(port, f"CONNECT 127.0.0.1:{up_port} HTTP/1.1\r\nHost: x\r\n\r\n".encode(), b"hello")
        assert ok.startswith(b"HTTP/1.1 200") and ok.endswith(b"upstream saw hello")
        for head in (b"CONNECT 127.0.0.1:9 HTTP/1.1\r\n\r\n",                     # another port
                     b"CONNECT example.com:443 HTTP/1.1\r\n\r\n",                 # another host
                     b"GET http://127.0.0.1:%d/ HTTP/1.1\r\n\r\n" % up_port,      # not a tunnel
                     b"GET / HTTP/1.1\r\nHost: door\r\n\r\n"):                   # probing the door itself
            assert (await _request(port, head)).startswith(b"HTTP/1.1 403")


@pytest.fixture
def anyio_backend():
    return "asyncio"
