"""Where a harness runs: one interface, two runtimes. Docker (docker.py) runs it in its sandbox's
image behind the egress door; local (local.py) runs it as a plain process on the host, for
development and tests, with no isolation and no egress rule.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Protocol

from .models import Sandbox
from .runner import Mounts, Prepared


@dataclass(frozen=True)
class Job:
    id: str
    prepared: Prepared
    workspace: Path
    harness_dir: Path
    image: str | None                                # the sandbox's image, already built; None for local
    egress: list[str]                                # host:port the run may reach


class Process:
    """One running harness: its stdout and stderr as they come, its exit code, and how to stop
    it. A timer stops it at the harness's timeout."""

    def __init__(self, proc: asyncio.subprocess.Process, timeout_s: int, kill: Callable[[], None],
                 cleanup: Callable[[], Awaitable[None]] | None = None):
        self.proc, self._kill, self._cleanup = proc, kill, cleanup
        self.timed_out = self.cancelled = False
        self._loop = asyncio.get_running_loop()
        self._timer = self._loop.call_later(timeout_s, self._end, "timeout")

    async def chunks(self, stderr: bool = False) -> AsyncIterator[bytes]:
        """Its stdout, or with `stderr` its stderr, as it arrives."""
        stream = self.proc.stderr if stderr else self.proc.stdout
        assert stream
        while chunk := await stream.read(65536):
            yield chunk

    async def wait(self) -> int:
        code = await self.proc.wait()
        self._timer.cancel()
        if self._cleanup:
            await self._cleanup()
        return code

    def cancel(self) -> None:
        """Safe from any thread: the kill itself runs on the event loop the process belongs to."""
        self._loop.call_soon_threadsafe(self._end, "cancelled")

    def _end(self, why: str) -> None:
        if self.proc.returncode is not None:
            return
        setattr(self, "timed_out" if why == "timeout" else "cancelled", True)
        self._kill()


class Runtime(Protocol):
    name: str
    def mounts(self, workspace: Path, harness_dir: Path) -> Mounts: ...
    async def image(self, sandbox: Sandbox) -> str | None: ...
    async def start(self, job: Job) -> Process: ...
    async def recover(self) -> None: ...             # at startup: remove whatever runs lost to a restart left behind


async def spawn(argv: list[str], env: dict[str, str], cwd: Path | None, stdin: bytes) -> asyncio.subprocess.Process:
    """Start a process in its own process group, stdout and stderr piped, stdin written and closed."""
    proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                                                start_new_session=True)
    assert proc.stdin
    try:
        proc.stdin.write(stdin)
        await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError, RuntimeError):
        pass                                         # it exited without reading stdin, which it need not read
    return proc
