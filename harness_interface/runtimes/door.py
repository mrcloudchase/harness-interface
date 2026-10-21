"""Layer 1: the egress door, a sandbox's only way out. Two listeners in one process, run in a container of
its own on the sandbox's network:

- the CONNECT door tunnels to an allowlist of host:port and refuses anything else with a 403. TLS
  stays end to end, so it sees nothing; it resolves names itself, so the sandbox needs no DNS.
- the provider gateway is a plain-HTTP reverse proxy to one upstream. A request must present the
  session's token, and only it, as its credential; the gateway swaps it for the real key in the
  header the API shape uses (none, for a `none` upstream that adds its own) and forwards over TLS. The real key never enters the sandbox. Once an
  answer has begun, an upstream failure only closes the connection.

It logs one line per decision (host, method and path; never a query, token or key) on stderr. It runs
as a script, standard library only, and takes the gateway's token and key as two lines on stdin,
never from its arguments or environment:
    python3 door.py LISTEN [HOST ...] [--gateway LISTEN UPSTREAM_URL API]
"""
from __future__ import annotations

import asyncio
import hmac
import ssl
import sys
from urllib.parse import urlsplit

READY = "door listening"
DOOR_PORT, GATEWAY_PORT = 3128, 8080
APIS = ("anthropic-messages", "openai-responses", "openai-chat")
KEYLESS = "none"                                     # the upstream adds its own credential
END = b"\r\n\r\n"
REFUSED = b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
UNAUTHORIZED = b"HTTP/1.1 401 Unauthorized\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
BAD_GATEWAY = b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
ESTABLISHED = b"HTTP/1.1 200 Connection established\r\n\r\n"
AUTH_HEADERS = {"x-api-key", "authorization", "api-key"}
HOP_HEADERS = {"host", "connection", "proxy-connection", "keep-alive", "proxy-authorization", "te", "upgrade"}
FAILURES = (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, OSError, ValueError)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def normalize(host: str) -> str:
    """'api.x.com' -> 'api.x.com:443'; a URL -> its host:port; a host with a port keeps it."""
    host = host.strip().lower().rstrip("/")
    if host.startswith(("https://", "http://")):
        u = urlsplit(host)
        return f"{u.hostname}:{u.port or (443 if u.scheme == 'https' else 80)}"
    return host if ":" in host else f"{host}:443"


async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    """Copy bytes until `src` ends, then close `dst`."""
    try:
        while chunk := await src.read(65536):
            dst.write(chunk)
            await dst.drain()
    finally:
        dst.close()


class Door:
    def __init__(self, allowed: list[str]):
        self.allowed = {normalize(h) for h in allowed if h.strip()}

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(END), timeout=10)
            words = head.split(b"\r\n", 1)[0].decode(errors="replace").split()
            target = words[1].lower() if len(words) == 3 and words[0] == "CONNECT" else ""
            log(f"door {'allow' if target in self.allowed else 'deny'} {target or '(not a CONNECT)'}")
            if target not in self.allowed:
                writer.write(REFUSED)
                await writer.drain()
                return
            host, port = target.rsplit(":", 1)
            try:
                up_r, up_w = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout=15)
            except (OSError, TimeoutError):
                writer.write(BAD_GATEWAY)
                await writer.drain()
                return
            writer.write(ESTABLISHED)
            await writer.drain()
            await asyncio.gather(pipe(reader, up_w), pipe(up_r, writer), return_exceptions=True)
        except FAILURES:
            pass
        finally:
            writer.close()


class Gateway:
    def __init__(self, upstream: str, api: str, token: str, key: str, tls: ssl.SSLContext | None = None):
        u = urlsplit(upstream)
        if u.scheme != "https" or not u.hostname:
            raise ValueError(f"the upstream must be https://host: {upstream!r}")
        if api not in (*APIS, KEYLESS):
            raise ValueError(f"unknown API shape {api!r}")
        self.host, self.port = u.hostname, u.port or 443
        self.authority = self.host if self.port == 443 else f"{self.host}:{self.port}"
        self._token = token
        self._auth = ("" if api == KEYLESS else f"x-api-key: {key}" if api == "anthropic-messages"
                      else f"Authorization: Bearer {key}")
        self._tls = tls or ssl.create_default_context()

    def admits(self, headers: list[tuple[str, str]]) -> bool:
        """Every credential it presents is the session's token, and it presents one."""
        presented = [v[7:].strip() if v.lower().startswith("bearer ") else v for k, v in headers
                     if k.lower() in AUTH_HEADERS]
        return bool(presented) and all(hmac.compare_digest(p.encode(), self._token.encode()) for p in presented)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        answered = False                             # once the answer has begun, a failure only closes
        try:
            lines = (await asyncio.wait_for(reader.readuntil(END), timeout=30)).decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            path = target.split("?", 1)[0]
            headers = [(k.strip(), v.strip()) for k, v in (line.split(":", 1) for line in lines[1:] if ":" in line)]
            if not self.admits(headers):
                log(f"gateway refuse {method} {path}")
                writer.write(UNAUTHORIZED)
                await writer.drain()
                return
            up_r, up_w = await asyncio.wait_for(asyncio.open_connection(
                self.host, self.port, ssl=self._tls, server_hostname=self.host), timeout=15)
            kept = [f"{k}: {v}" for k, v in headers if k.lower() not in AUTH_HEADERS | HOP_HEADERS]
            up_w.write("\r\n".join([f"{method} {target} HTTP/1.1", f"Host: {self.authority}", "Connection: close",
                                    *([self._auth] if self._auth else []), *kept, "", ""]).encode("latin-1"))
            await up_w.drain()
            body = asyncio.ensure_future(pipe(reader, up_w))
            body.add_done_callback(lambda t: t.cancelled() or t.exception())   # its failure is the answer's
            try:
                answer = (await up_r.readuntil(END)).decode("latin-1").split("\r\n")
                log(f"gateway {method} {path} -> {answer[0].split(' ')[1] if ' ' in answer[0] else '?'}")
                kept_answer = [line for line in answer[1:]
                               if line and line.split(":", 1)[0].strip().lower() not in ("connection", "keep-alive")]
                writer.write("\r\n".join([answer[0], *kept_answer, "Connection: close", "", ""]).encode("latin-1"))
                answered = True
                await pipe(up_r, writer)
            finally:
                body.cancel()
                up_w.close()
        except FAILURES as e:
            log(f"gateway error {type(e).__name__}")
            if not answered:
                writer.write(BAD_GATEWAY)
        finally:
            writer.close()


async def serve(listen: str, allowed: list[str], gateway: Gateway | None, gateway_listen: str) -> None:
    servers = []
    for handle, address in ((Door(allowed).handle, listen), *(((gateway.handle, gateway_listen),) if gateway else ())):
        host, port = address.rsplit(":", 1)
        servers.append(await asyncio.start_server(handle, host, int(port)))
    log(READY)
    await asyncio.gather(*(s.serve_forever() for s in servers))


def main(argv: list[str]) -> None:
    gateway, gateway_listen = None, ""
    if "--gateway" in argv:
        i = argv.index("--gateway")
        gateway_listen, upstream, api = argv[i + 1:i + 4]
        argv = argv[:i]
        token, key = sys.stdin.readline().strip(), sys.stdin.readline().strip()
        if not token or (not key and api != KEYLESS):
            raise SystemExit("door: the gateway needs a token and a key, one line each, on stdin")
        gateway = Gateway(upstream, api, token, key)
    asyncio.run(serve(argv[0], argv[1:], gateway, gateway_listen))


if __name__ == "__main__":
    main(sys.argv[1:])
