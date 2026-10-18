"""Layer 1: one operating-system process as an Execution. The only code that spawns a process,
streams its output, feeds its input, times it out and cancels it; the local and Docker runtimes
both run their process through it.

The process gets its own process group, so a timeout or a cancel stops everything it started. Its
output is read as soon as it is written, whether or not anyone is consuming events, so a process
never blocks on a full pipe and wait() never waits on a reader.
"""
from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Mapping, Sequence

from ..errors import Invalid
from ..execution import Event, Execution, NeverStarted, Outcome

STREAMS = ("stdout", "stderr")
GONE = (BrokenPipeError, ConnectionResetError, RuntimeError)   # it stopped reading; RuntimeError: a closed transport


class ProcessExecution:
    def __init__(self, proc: asyncio.subprocess.Process, timeout_s: float | None, interactive: bool,
                 kill: Callable[[], Awaitable[object] | None] | None,
                 cleanup: Callable[[], Awaitable[None]] | None):
        self._proc, self._cleanup = proc, cleanup
        self._kill = kill or self._kill_group
        self._loop = asyncio.get_running_loop()
        self._ended_by: str | None = None            # "timed_out" or "cancelled", when we ended it
        self._input_open = interactive
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._pumps = [asyncio.create_task(self._pump(name, getattr(proc, name))) for name in STREAMS]
        self._timer = self._loop.call_later(timeout_s, self._end, "timed_out") if timeout_s else None
        self._finished: asyncio.Future[Outcome] | None = None
        self._iterated = False
        self._chores: set[asyncio.Future] = set()    # kills in flight, kept until done

    @classmethod
    async def spawn(cls, argv: Sequence[str], *, env: Mapping[str, str], cwd: Path | None, input: bytes,
                    interactive: bool, timeout_s: float | None,
                    kill: Callable[[], Awaitable[object] | None] | None = None,
                    cleanup: Callable[[], Awaitable[None]] | None = None) -> Execution:
        """Start the process and write its input. A process that can't start is a NeverStarted."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, cwd=cwd, env=dict(env), start_new_session=True,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except OSError as e:
            if cleanup:
                await cleanup()
            return NeverStarted(f"could not start {argv[0]}: {e}")
        execution = cls(proc, timeout_s, interactive, kill, cleanup)
        try:
            await execution._write(input)
            if not interactive:
                execution._close_input()
        except BaseException:                        # cancelled while starting: leave nothing running
            execution._end("cancelled")
            await execution.wait()
            raise
        return execution

    # the Execution interface
    async def events(self) -> AsyncIterator[Event]:
        assert not self._iterated, "events() can be iterated once"
        self._iterated = True
        open_streams = len(STREAMS)
        while open_streams:
            event = await self._queue.get()
            if event is None:
                open_streams -= 1
            else:
                yield event

    async def send(self, data: bytes) -> None:
        if not self._input_open or self._proc.returncode is not None:
            raise Invalid("its input is closed")
        await self._write(data)

    async def end_input(self) -> None:
        self._close_input()

    def cancel(self) -> None:
        self._loop.call_soon_threadsafe(self._end, "cancelled")

    async def wait(self) -> Outcome:
        if self._finished is None:
            self._finished = asyncio.ensure_future(self._finish())
        return await asyncio.shield(self._finished)

    # the process
    async def _pump(self, name: str, stream: asyncio.StreamReader) -> None:
        try:
            while chunk := await stream.read(65536):
                self._queue.put_nowait(Event(name, chunk))
        finally:
            self._queue.put_nowait(None)

    async def _write(self, data: bytes) -> None:
        stdin = self._proc.stdin
        assert stdin is not None
        try:
            stdin.write(data)
            await stdin.drain()
        except GONE:
            self._input_open = False                 # it exited without reading, which it need not do

    def _close_input(self) -> None:
        self._input_open = False
        try:
            self._proc.stdin.close()
        except GONE:
            pass

    def _end(self, why: str) -> None:
        if self._proc.returncode is not None or self._ended_by:
            return                                   # it ended already: the first reason stands
        self._ended_by = why
        result = self._kill()
        if result is not None:
            chore = asyncio.ensure_future(result)
            self._chores.add(chore)
            chore.add_done_callback(self._chores.discard)

    def _kill_group(self) -> None:
        try:
            os.killpg(self._proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    async def _finish(self) -> Outcome:
        await asyncio.gather(*self._pumps)           # every byte it wrote is read before it is over
        code = await self._proc.wait()
        if self._timer:
            self._timer.cancel()
        if self._chores:
            await asyncio.gather(*self._chores, return_exceptions=True)
        if self._cleanup:
            await self._cleanup()
        if self._ended_by == "timed_out":
            return Outcome.timed_out()
        if self._ended_by == "cancelled":
            return Outcome.cancelled()
        return Outcome.exited(code)
