"""The process contract, and nothing else.

Prepare: render the harness's files and env, add the HI_* variables, write request.json.
Execute: spawn argv in the workspace, stream stdout, keep stderr as the log, kill at the cap.
What the harness wrote to HI_OUTPUT is read back by the caller when the process is done.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from .models import Harness, RunRequest, Session
from .storage import SecretStore
from .template import render, render_obj
from .workspace import Workspace

OUTPUT_FILE = ".hi/output.json"
REQUEST_FILE = ".hi/request.json"


@dataclass
class Prepared:
    argv: list[str]
    env: dict[str, str]
    cwd: Path
    stdin: bytes
    timeout_s: int


class Runner:
    def __init__(self, secrets: SecretStore):
        self.secrets = secrets

    def prepare(self, harness: Harness, request: RunRequest, session: Session, ws: Workspace) -> Prepared:
        ctx = {
            "request": {**request.model_dump(), "file_names": [f.name for f in request.files]},
            "workspace": str(ws.path),
            "harness_dir": harness.dir or "",
            "session": session.model_dump(),
        }
        for rel, content in harness.files.items():
            ws.write(render(rel, ctx), render(content, ctx))
        body = request.model_dump_json(indent=2)
        ws.write(REQUEST_FILE, body)
        env = {**os.environ, **render_obj(harness.run.env, ctx)}
        for name in harness.secrets:
            value = self.secrets.get(name)
            if value is None:
                raise LookupError(f"secret '{name}' is not set (PUT /secrets/{name})")
            env[name] = value
        env.update({
            "HI_REQUEST": str(ws.path / REQUEST_FILE),
            "HI_OUTPUT": str(ws.path / OUTPUT_FILE),
            "HI_WORKSPACE": str(ws.path),
            "HI_HARNESS_DIR": harness.dir or "",
            "HI_TASK": request.task,
            "HI_MODEL": request.model or "",
            "HI_SESSION_ID": session.session_id or "",
        })
        return Prepared(argv=render_obj(harness.run.argv, ctx), env=env, cwd=ws.path,
                        stdin=body.encode(), timeout_s=harness.run.timeout_s)


@dataclass
class Execution:
    """One spawned process. `chunks()` streams stdout and keeps a copy at out_path; `wait()` gives
    the exit code; stderr goes to log_path."""
    prepared: Prepared
    log_path: Path
    out_path: Path
    proc: asyncio.subprocess.Process | None = None
    timed_out: bool = False
    cancelled: bool = False
    _timer: asyncio.TimerHandle | None = field(default=None, repr=False)

    async def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = open(self.log_path, "wb")
        self.proc = await asyncio.create_subprocess_exec(
            *self.prepared.argv, cwd=self.prepared.cwd, env=self.prepared.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log,
            start_new_session=True)
        log.close()
        self.proc.stdin.write(self.prepared.stdin)
        await self.proc.stdin.drain()
        self.proc.stdin.close()
        loop = asyncio.get_running_loop()
        self._timer = loop.call_later(self.prepared.timeout_s, self._kill, "timeout")

    async def chunks(self) -> AsyncIterator[bytes]:
        assert self.proc and self.proc.stdout
        with open(self.out_path, "wb") as out:
            while chunk := await self.proc.stdout.read(65536):
                out.write(chunk)
                yield chunk

    async def wait(self) -> int:
        assert self.proc
        code = await self.proc.wait()
        if self._timer:
            self._timer.cancel()
        return code

    def cancel(self) -> None:
        self._kill("cancelled")

    def _kill(self, why: str) -> None:
        if not self.proc or self.proc.returncode is not None:
            return
        setattr(self, "timed_out" if why == "timeout" else "cancelled", True)
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def read_output(ws: Workspace) -> dict:
    p = ws.path / OUTPUT_FILE
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}
