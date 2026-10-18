"""Layer 3: one turn of a harness, on any runtime. Prepare its workspace, run it, then read what it
reported and what it changed. This is how the library runs a harness folder, and how the platform
runs every turn.

    turn = await Turn.start(runtime, harness, provider, Request("Fix the failing test"), workspace, scripts)
    async for event in turn.events():
        ...
    result = await turn.result()

A turn can be cancelled at any point, from any thread: while its runtime is still setting up, the
harness never starts; once it runs, it is stopped.
"""
from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import AsyncIterator

from ..execution import Event, Execution, Outcome, Runtime
from ..workspace import Workspace
from .contract import Harness, Provider, Request, Result, collect, prepare


class Turn:
    def __init__(self, workspace: Workspace, base: str, starting: asyncio.Task[Execution]):
        self.workspace, self.base = workspace, base
        self._starting = starting
        self._loop = asyncio.get_running_loop()
        self._result: asyncio.Future[Result] | None = None

    @classmethod
    async def start(cls, runtime: Runtime, harness: Harness, provider: Provider, request: Request,
                    workspace: Path, scripts: Path) -> Turn:
        """Prepare the workspace and start the run; returns once it is starting. A request the
        contract can't carry out (an unknown placeholder, a path outside the workspace) raises here,
        before anything runs."""
        ws = Workspace(workspace)

        def setup() -> tuple:
            ws.init()
            spec = prepare(harness, provider, request, ws, scripts)
            return spec, ws.snapshot("prepare")      # the baseline: only what the harness writes counts as its change
        spec, base = await asyncio.to_thread(setup)
        return cls(ws, base, asyncio.create_task(runtime.start(spec)))

    async def events(self) -> AsyncIterator[Event]:
        """What the harness prints, as it prints it."""
        execution = await self._execution()
        if execution:
            async for event in execution.events():
                yield event

    def cancel(self) -> None:
        """Stop the turn. Safe from any thread."""
        self._loop.call_soon_threadsafe(self._cancel)

    async def result(self) -> Result:
        if self._result is None:
            self._result = asyncio.ensure_future(self._finish())
        return await asyncio.shield(self._result)

    def _cancel(self) -> None:
        if not self._starting.done():
            self._starting.cancel()                  # still setting up: the harness never starts
        elif not self._starting.cancelled() and self._starting.exception() is None:
            self._starting.result().cancel()

    async def _execution(self) -> Execution | None:
        try:
            return await asyncio.shield(self._starting)
        except asyncio.CancelledError:
            if self._starting.cancelled():
                return None
            raise

    async def _finish(self) -> Result:
        execution = await self._execution()
        outcome = await execution.wait() if execution else Outcome.cancelled()

        def done() -> Result:
            result = collect(outcome, self.workspace)
            files, deleted = self.workspace.changes()
            commit = self.workspace.snapshot("turn")
            return dataclasses.replace(result, files=tuple(files), deleted=tuple(deleted), base=self.base, commit=commit)
        return await asyncio.to_thread(done)
