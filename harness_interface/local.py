"""The local runtime: the harness as a plain process on the host, in its workspace. No isolation
and no egress rule; every record says `runtime: local`."""
from __future__ import annotations

import os
import signal
from pathlib import Path

from .models import Sandbox
from .runner import Mounts
from .runtime import Job, Process, spawn


class LocalRuntime:
    name = "local"

    def mounts(self, workspace: Path, harness_dir: Path) -> Mounts:
        return Mounts(workspace=str(workspace), harness=str(harness_dir))

    async def image(self, sandbox: Sandbox) -> None:
        return None

    async def start(self, job: Job) -> Process:
        p = job.prepared
        proc = await spawn(p.argv, {**os.environ, **p.env}, job.workspace, p.stdin, job.log_path)

        def kill() -> None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        return Process(proc, p.timeout_s, kill)

    async def recover(self) -> None:
        return None                                  # a local process does not outlive the server
