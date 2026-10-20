"""Layer 3: one response, on any runtime.

`Response.start` prepares the workspace (the contract's `prepare`), asks the Placement for a runtime
with the folder's mounts, hosts and provider, and starts `bash run.sh`. While it runs, its events are
the harness's stdout and stderr as written (and the door's log, under Docker) plus a `steer` event for
each steer it was sent; they are kept whether or not anyone reads them. `steer` writes one line, and
raises Invalid unless the harness is `steered`, no stop was asked for, and the line was delivered.
`stop` asks for a graceful stop (SIGINT, through tini under Docker) and kills after the folder's
`run.stop_timeout_s` or the timeout given; `run.timeout_s` brings the same stop. `result` is the
contract's `collect`, once the process has ended and every event is in.

Nothing is left behind on any path: a cancelled start leaves nothing running, and cancelling `result`
kills the response and waits for its teardown before the cancel goes on.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import AsyncIterator

from ..errors import Invalid
from ..execution import Event, Execution
from ..runtimes.docker import Provider, whole
from ..workspace import Workspace
from .contract import Prepared, Request, Result, collect, prepare
from .folder import HarnessFolder, check_provider_url
from .install import Installed
from .placement import Placement


class Response:
    def __init__(self, folder: HarnessFolder, workspace: Workspace, prepared: Prepared, execution: Execution):
        self.folder, self.workspace, self.prepared = folder, workspace, prepared
        self._execution = execution
        self.steers_sent = 0
        self.stopping: str | None = None             # why a stop was asked for: "requested" or "timeout"
        self._events: asyncio.Queue[Event | None] = asyncio.Queue()
        self._iterated = False
        self._timer = asyncio.get_running_loop().call_later(folder.run.timeout_s, self._stop, "timeout", None)
        self._pump = asyncio.ensure_future(self._drain())
        self._finished = asyncio.ensure_future(self._finish())

    @classmethod
    async def start(cls, folder: HarnessFolder, installed: Installed, workspace: Workspace, request: Request, *,
                    placement: Placement, rundir: Path, provider: Provider | None = None,
                    new_session: bool = False) -> Response:
        """Start one response of `folder` in `workspace`. The provider's credential mode is the folder's
        (`run.credential`); under the gateway it must carry the session's token."""
        if provider:
            if provider.api not in folder.apis:
                raise Invalid(f"{folder.name} speaks {', '.join(folder.apis)}, not {provider.api}")
            check_provider_url(provider.url, provider.api)
            provider = replace(provider, credential=folder.run.credential)
        runtime = placement.runtime(installed.image, read_only=(folder.path, installed.path), writable=(rundir,),
                                    egress=folder.run.egress, provider=provider)
        prepared = await whole(asyncio.to_thread(
            prepare, folder, workspace, request, rundir=rundir, tools=installed.path, path=placement.path,
            provider_url=runtime.provider_url, provider_api=provider.api if provider else None,
            key_file=runtime.key_path, new_session=new_session))
        return cls(folder, workspace, prepared, await runtime.start(prepared.spec))

    async def events(self) -> AsyncIterator[Event]:
        """Its events as they come, kept from its start; the iteration ends when it does. Iterate once."""
        assert not self._iterated, "events() can be iterated once"
        self._iterated = True
        while (event := await self._events.get()) is not None:
            yield event

    async def steer(self, text: str) -> None:
        """Put more text into the work in progress, or raise Invalid saying why it can't be."""
        if self.folder.run.interrupt != "steered":
            raise Invalid(f"{self.folder.name} takes no steers: it is {self.folder.run.interrupt}")
        if not isinstance(text, str) or not text.strip():
            raise Invalid("a steer is some text")
        if self.stopping:
            raise Invalid("it is stopping")
        await self._execution.send((json.dumps(text) + "\n").encode())
        self.steers_sent += 1
        self._events.put_nowait(Event("steer", text.encode()))

    def stop(self, timeout_s: float | None = None) -> None:
        """Stop gracefully; kill after `timeout_s` (by default the folder's run.stop_timeout_s). A later
        stop only brings the kill closer."""
        self._stop("requested", timeout_s)

    async def result(self) -> Result:
        try:
            return await asyncio.shield(self._finished)
        except asyncio.CancelledError:
            self._execution.kill()
            await asyncio.wait([self._finished])
            raise

    def _stop(self, why: str, timeout_s: float | None) -> None:
        self.stopping = self.stopping or why
        self._execution.stop(self.folder.run.stop_timeout_s if timeout_s is None else timeout_s)

    async def _drain(self) -> None:
        try:
            async for event in self._execution.events():
                self._events.put_nowait(event)
        finally:
            self._events.put_nowait(None)

    async def _finish(self) -> Result:
        outcome = await self._execution.wait()
        self._timer.cancel()
        await self._pump
        return await whole(asyncio.to_thread(collect, self.folder, self.workspace, self.prepared, outcome=outcome,
                                             stop=self.stopping, steers_sent=self.steers_sent))
