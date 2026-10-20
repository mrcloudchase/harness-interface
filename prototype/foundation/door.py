"""The egress door, two listeners in one process (one door container per session):

- CONNECT door (harness_interface.runtimes.egress.Door, reused): tunnels to an allowlist of
  host:port and refuses everything else with 403. Logs each decision (host only).
- Provider gateway (new; the recommended secret mechanism): a plain-HTTP reverse proxy to ONE
  upstream. The sandbox calls http://<door>:8080<path> with a per-session placeholder token as its
  "key"; the gateway checks the token, replaces it with the real key in the header the API shape
  uses, and forwards over TLS. The real key never enters the sandbox.

    python3 door.py LISTEN [HOST ...]                       # CONNECT door only
    python3 door.py LISTEN [HOST ...] --gateway LISTEN UPSTREAM_URL API   # + gateway;
        reads two lines from stdin first: the placeholder token, then the key (never argv/env)
"""
from __future__ import annotations

import asyncio
import os
import ssl
import sys
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))            # in the door container
sys.path.insert(0, "/home/user/harness-interface/harness_interface/runtimes")   # on the host
from egress import ESTABLISHED, READY, REFUSED, Door, normalize  # noqa: E402,F401

AUTH_HEADERS = {"x-api-key", "authorization", "api-key"}
HOP_HEADERS = {"host", "connection", "proxy-connection", "keep-alive", "proxy-authorization", "te", "upgrade"}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)                # never stdout: hirun prints its result there


class LoggingDoor(Door):
    """Door, plus one log line per CONNECT decision."""

    async def handle(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError):
            writer.close()
            return
        line = head.split(b"\r\n", 1)[0].decode(errors="replace").split()
        target = line[1].lower() if len(line) == 3 and line[0] == "CONNECT" else f"{line[:1]} (not CONNECT)"
        log(f"door {'allow' if target in self.allowed else 'deny'} {target}")
        replay = asyncio.StreamReader()
        replay.feed_data(head)
        await super().handle(_Chain(replay, reader), writer)


class _Chain:
    """A reader that yields the already-read head, then the socket."""

    def __init__(self, first: asyncio.StreamReader, rest: asyncio.StreamReader):
        self.first, self.rest = first, rest

    async def readuntil(self, sep):
        return await self.first.readuntil(sep)

    async def read(self, n=-1):
        return await self.rest.read(n)


class Gateway:
    """Reverse proxy to one upstream that swaps a placeholder token for the real key."""

    def __init__(self, upstream: str, api: str, token: str, key: str):
        u = urlsplit(upstream)
        assert u.scheme == "https" and u.hostname, f"upstream must be https://host: {upstream!r}"
        self.host, self.port = u.hostname, u.port or 443
        self.token, self.key = token, key
        self.auth = ("x-api-key", key) if api == "anthropic-messages" else ("authorization", f"Bearer {key}")
        self.tls = ssl.create_default_context()

    def presented(self, headers: list[tuple[str, str]]) -> str:
        for k, v in headers:
            if k.lower() in AUTH_HEADERS:
                return v.split(" ", 1)[1].strip() if v.lower().startswith("bearer ") else v.strip()
        return ""

    async def handle(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
            lines = head.decode("latin-1").split("\r\n")
            method, path, _ = lines[0].split(" ", 2)
            headers = [tuple(x.strip() for x in ln.split(":", 1)) for ln in lines[1:] if ":" in ln]
            if self.presented(headers) != self.token:
                log(f"gateway refuse {method} {path.split('?')[0]} (no session token)")
                writer.write(b"HTTP/1.1 401 Unauthorized\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            kept = [(k, v) for k, v in headers if k.lower() not in AUTH_HEADERS | HOP_HEADERS]
            out = [f"{method} {path} HTTP/1.1", f"Host: {self.host}", "Connection: close", ": ".join(self.auth),
                   *(f"{k}: {v}" for k, v in kept)]
            up_r, up_w = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, ssl=self.tls, server_hostname=self.host), timeout=15)
            up_w.write(("\r\n".join(out) + "\r\n\r\n").encode("latin-1"))
            await up_w.drain()
            body = asyncio.ensure_future(Door._pipe(reader, up_w))
            resp = await up_r.readuntil(b"\r\n\r\n")
            rl = resp.decode("latin-1").split("\r\n")
            log(f"gateway {method} {path.split('?')[0]} -> {rl[0].split(' ')[1] if ' ' in rl[0] else '?'}")
            rh = [ln for ln in rl[1:] if ln and ln.split(":", 1)[0].strip().lower() not in ("connection", "keep-alive")]
            writer.write(("\r\n".join([rl[0], *rh, "Connection: close"]) + "\r\n\r\n").encode("latin-1"))
            await Door._pipe(up_r, writer)
            body.cancel()
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ConnectionError,
                OSError, ValueError) as e:
            log(f"gateway error {type(e).__name__}")
            try:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except Exception:  # noqa: BLE001
                pass
        finally:
            writer.close()


async def serve(listen: str, allowed: list[str], gateway: Gateway | None = None, gateway_listen: str = "") -> None:
    host, port = listen.rsplit(":", 1)
    servers = [await asyncio.start_server(LoggingDoor(allowed).handle, host, int(port))]
    if gateway:
        ghost, gport = gateway_listen.rsplit(":", 1)
        servers.append(await asyncio.start_server(gateway.handle, ghost, int(gport)))
    log(READY)
    await asyncio.gather(*(s.serve_forever() for s in servers))


def main(argv: list[str]) -> None:
    gateway, glisten = None, ""
    if "--gateway" in argv:
        i = argv.index("--gateway")
        glisten, upstream, api = argv[i + 1:i + 4]
        argv = argv[:i]
        token, key = sys.stdin.readline().strip(), sys.stdin.readline().strip()
        assert token and key, "gateway needs a token and a key on stdin"
        gateway = Gateway(upstream, api, token, key)
    asyncio.run(serve(argv[0], argv[1:], gateway, glisten))


if __name__ == "__main__":
    main(sys.argv[1:])
