"""Layer 1: the egress door, a CONNECT-only tunnel to an allowlist of hosts, and nothing else.

A sandbox has no route out but this. It accepts `CONNECT host:port` for a host on the list, opens
the tunnel, and copies bytes both ways; TLS stays end to end, so it sees nothing. Any other
request, host or method gets a 403. It resolves names itself, so the sandbox needs no DNS.

Runs as a library (tests) or as a script inside the door container, where it prints "door listening" once
it accepts connections:
    python3 egress.py 0.0.0.0:3128 api.deepseek.com:443 pypi.org:443
"""
from __future__ import annotations

import asyncio
import sys

READY = "door listening"
REFUSED = b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
ESTABLISHED = b"HTTP/1.1 200 Connection established\r\n\r\n"


def normalize(host: str) -> str:
    """'api.x.com' -> 'api.x.com:443'; a host with a port keeps it."""
    host = host.strip().lower().rstrip("/")
    if host.startswith("https://") or host.startswith("http://"):
        from urllib.parse import urlsplit
        u = urlsplit(host)
        return f"{u.hostname}:{u.port or (443 if u.scheme == 'https' else 80)}"
    return host if ":" in host else f"{host}:443"


class Door:
    def __init__(self, allowed: list[str]):
        self.allowed = {normalize(h) for h in allowed if h.strip()}

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            line = head.split(b"\r\n", 1)[0].decode(errors="replace").split()
            target = line[1].lower() if len(line) == 3 and line[0] == "CONNECT" else ""
            if target not in self.allowed:
                writer.write(REFUSED)
                await writer.drain()
                return
            host, port = target.rsplit(":", 1)
            try:
                up_r, up_w = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout=15)
            except (OSError, asyncio.TimeoutError):
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            writer.write(ESTABLISHED)
            await writer.drain()
            await asyncio.gather(self._pipe(reader, up_w), self._pipe(up_r, writer))
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    @staticmethod
    async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while chunk := await src.read(65536):
                dst.write(chunk)
                await dst.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            try:
                dst.close()
            except Exception:  # noqa: BLE001 — closing a closed socket is nothing
                pass

    async def serve(self, host: str, port: int) -> asyncio.base_events.Server:
        return await asyncio.start_server(self.handle, host, port)


async def _main(listen: str, allowed: list[str]) -> None:
    host, port = listen.rsplit(":", 1)
    server = await Door(allowed).serve(host, int(port))
    print(READY, flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1], sys.argv[2:]))
