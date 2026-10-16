"""One request, end to end: decide, prepare, run, record. The HTTP layer only calls this."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import AsyncIterator

from .config import Settings
from .models import Decision, Harness, Run, RunRequest, Session
from .registry import Registry
from .router import make_router
from .runner import Execution, Runner, read_output
from .storage import JsonStore, SecretStore
from .workspace import Workspace


class RunService:
    def __init__(self, settings: Settings, registry: Registry, runner: Runner, secrets: SecretStore,
                 runs: JsonStore[Run], sessions: JsonStore[Session]):
        self.settings, self.registry, self.runner, self.secrets = settings, registry, runner, secrets
        self.runs, self.sessions = runs, sessions
        self.live: dict[str, Execution] = {}

    # ── decide ────────────────────────────────────────────────────────────────────────────────
    async def decide(self, request: RunRequest) -> tuple[Session, Harness, Decision | None]:
        if request.session:
            session = self.sessions.get(request.session)
            if not session:
                raise LookupError(f"no session {request.session}")
            return session, self._harness(session.harness), None
        if request.harness:
            decision = Decision(harness=request.harness, reason="pinned by request")
        else:
            route = self.registry.route()
            if not route:
                raise LookupError("no harness named and no route applied (PUT /route)")
            router = make_router(route, self.secrets, self.settings.jev_base_url, self.settings.jev_secret_name)
            decision = await router.choose(request, self.registry.cards())
        harness = self._harness(decision.harness)
        session = Session(harness=harness.name, workspace="")
        session.workspace = str(self.settings.workspaces / session.id)
        return self.sessions.put(session.id, session), harness, decision

    def _harness(self, name: str) -> Harness:
        h = self.registry.get(name)
        if not h:
            raise LookupError(f"no harness '{name}'")
        return h

    # ── run ───────────────────────────────────────────────────────────────────────────────────
    async def start(self, request: RunRequest) -> tuple[Run, Execution, Workspace]:
        session, harness, decision = await self.decide(request)
        ws = Workspace(Path(session.workspace))
        ws.init(request.files)
        prepared = self.runner.prepare(harness, request, session, ws)
        ws.commit("prepare")                      # baseline: only what the harness itself writes counts as produced
        run = Run(session=session.id, harness=harness.name, request=request, decision=decision)
        execution = Execution(prepared, self.settings.logs / f"{run.id}.log")
        await execution.start()
        self.live[run.id] = execution
        return self.runs.put(run.id, run), execution, ws

    async def stream(self, run: Run, execution: Execution, ws: Workspace) -> AsyncIterator[bytes]:
        try:
            async for chunk in execution.chunks():
                yield chunk
        finally:
            await self.finish(run, execution, ws)

    async def finish(self, run: Run, execution: Execution, ws: Workspace) -> Run:
        code = await execution.wait()
        self.live.pop(run.id, None)
        output = read_output(ws)
        run.exit_code, run.output, run.usage = code, output, output.get("usage")
        run.status = ("timeout" if execution.timed_out else "cancelled" if execution.cancelled
                      else str(output.get("status") or ("ok" if code == 0 else "fail")))
        run.files = ws.changed()
        if run.request.check:
            run.check = self._check(run.request.check, ws)
        ws.commit(f"run {run.id}")
        run.ended_at = time.time()
        run.latency_s = round(run.ended_at - run.started_at, 3)
        if output.get("session_id"):
            session = self.sessions.get(run.session)
            if session:
                session.session_id = str(output["session_id"])
                self.sessions.put(session.id, session)
        return self.runs.put(run.id, run)

    def _check(self, cmd: str, ws: Workspace) -> dict:
        try:
            done = subprocess.run(cmd, shell=True, cwd=ws.path, capture_output=True, text=True,
                                  timeout=self.settings.check_timeout_s)
            return {"cmd": cmd, "exit": done.returncode, "pass": done.returncode == 0,
                    "output": (done.stdout + done.stderr)[-2000:]}
        except subprocess.TimeoutExpired:
            return {"cmd": cmd, "exit": None, "pass": False, "output": "timed out"}

    def cancel(self, run_id: str) -> bool:
        ex = self.live.get(run_id)
        if not ex:
            return False
        ex.cancel()
        return True
