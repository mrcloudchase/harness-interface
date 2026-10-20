"""Layer 1: the local runtime. A process on this machine, in the spec's workspace, with the spec's
environment over the allowlisted part of this machine's, and loopback never proxied.

Its guarantee is no isolation: what runs can read, write and reach anything the user running it
can. Use it for programs you trust, such as a harness you are developing.

It may have one provider, as the Docker runtime may. Under the gateway the run reads a session token
from `key_path` and calls `provider_url`, a gateway on loopback that swaps the token for the key, so
the key stays in this process; in file mode the run reads the key there and calls the provider
itself. The URL and the path are the runtime's own, the same for every run of it, one run at a time;
the gateway listens and the credential exists only while a run does.
"""
from __future__ import annotations

import asyncio
import os
import socket
import ssl
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from ..execution import Execution, NeverStarted, Spec
from .docker import PREFIX, SECRETS, Provider, shred, whole
from .door import Gateway
from .process import ProcessExecution, host_env

LOOPBACK = ("127.0.0.1", "localhost")


def free_port() -> int:
    with socket.create_server(("127.0.0.1", 0)) as s:
        return s.getsockname()[1]


class LocalRuntime:
    def __init__(self, provider: Provider | None = None, *, ca_file: Path | None = None):
        self.provider, self.ca_file = provider, ca_file
        self._secrets = SECRETS / f"{PREFIX}{uuid.uuid4().hex[:12]}"
        self._port = free_port() if provider and provider.credential == "gateway" else None

    @property
    def provider_url(self) -> str | None:
        """The provider's base URL as the run must call it: the gateway's, at the same path, or its own."""
        if not self.provider:
            return None
        if self._port is None:
            return self.provider.url
        return f"http://127.0.0.1:{self._port}" + urlsplit(self.provider.url).path.rstrip("/")

    @property
    def key_path(self) -> Path | None:
        return self._secrets / "key" if self.provider else None

    async def start(self, spec: Spec) -> Execution:
        env = {**host_env(), **spec.env}
        hosts = {*env.get("NO_PROXY", env.get("no_proxy", "")).split(","), *LOOPBACK} - {""}
        env["NO_PROXY"] = env["no_proxy"] = ",".join(sorted(hosts))
        server: asyncio.AbstractServer | None = None
        made: list[Path] = []                        # the credential, once this run made it: never another run's

        async def cleanup() -> None:
            if server:
                server.close()
                await server.wait_closed()
            if made:
                await asyncio.to_thread(shred, self._secrets)
        try:
            if self.provider:
                await whole(asyncio.to_thread(self._write_credential, made))
                if self._port is not None:
                    server = await self._serve()
        except asyncio.CancelledError:
            await asyncio.shield(cleanup())
            raise
        except OSError as e:
            await asyncio.shield(cleanup())
            return NeverStarted(f"could not start the provider's gateway: {e}")
        return await ProcessExecution.spawn(spec.command, env=env, cwd=spec.workspace, input=spec.input,
                                            interactive=spec.interactive, timeout_s=spec.timeout_s,
                                            cleanup=cleanup if self.provider else None)

    async def recover(self) -> None:
        return None                                  # a local process does not outlive what started it

    def _write_credential(self, made: list[Path]) -> None:
        self._secrets.mkdir(mode=0o700)
        made.append(self._secrets)
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "w") as f:
            f.write(self.provider.token if self._port is not None else self.provider.key)

    async def _serve(self) -> asyncio.AbstractServer:
        p = self.provider
        tls = ssl.create_default_context(cafile=str(self.ca_file)) if self.ca_file else None
        return await asyncio.start_server(Gateway(p.url, p.api, p.token, p.key, tls).handle, "127.0.0.1", self._port)
