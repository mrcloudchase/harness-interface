"""One request, end to end: decide, prepare, run, record, judge. The HTTP layer only calls this."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import AsyncIterator

from . import evidence
from .config import Settings
from .models import Decision, Harness, Run, RunRequest, Session, Verdict
from .registry import Registry
from .router import make_judge, make_router
from .router.jev import JevRouter
from .runner import Execution, Runner, read_output
from .storage import JsonStore, SecretStore
from .workspace import Workspace

TEXT_FILE_BYTES = 64 * 1024   # a produced file larger than this is named to the judge, not shown


class RunService:
    def __init__(self, settings: Settings, registry: Registry, runner: Runner, secrets: SecretStore,
                 runs: JsonStore[Run], sessions: JsonStore[Session]):
        self.settings, self.registry, self.runner, self.secrets = settings, registry, runner, secrets
        self.runs, self.sessions = runs, sessions
        self.live: dict[str, Execution] = {}

    # ── cards: what the router chooses between ────────────────────────────────────────────────
    def cards(self) -> list[dict]:
        stats = evidence.summarize(self.runs.list())
        return [{**c, "stats": stats.get(c["name"]), "evidence": evidence.sentence(stats.get(c["name"]))}
                for c in self.registry.cards()]

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
            decision = await router.choose(request, self.cards())
        harness = self._harness(decision.harness)
        session = Session(harness=harness.name, workspace="")
        session.workspace = str(self.settings.workspaces / session.id)
        return self.sessions.put(session.id, session), harness, decision

    async def preview(self, request: RunRequest) -> dict:
        """What the route would do with this request, without running it: the exact Jev request
        body (None for a static route) and the decision."""
        route = self.registry.route()
        if not route:
            raise LookupError("no route applied (PUT /route)")
        router = make_router(route, self.secrets, self.settings.jev_base_url, self.settings.jev_secret_name)
        cards = self.cards()
        body = ({"model": route.model, "state": router.state(request), "questions": router.questions(cards)}
                if isinstance(router, JevRouter) else None)
        return {"engine": route.engine, "jev_request": body, "decision": (await router.choose(request, cards)).model_dump()}

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
        execution = Execution(prepared, self.log_path(run.id), self.out_path(run.id))
        await execution.start()
        self.live[run.id] = execution
        return self.runs.put(run.id, run), execution, ws

    def log_path(self, run_id: str) -> Path:
        return self.settings.logs / f"{run_id}.log"

    def out_path(self, run_id: str) -> Path:
        return self.settings.logs / f"{run_id}.out"

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
        run.verdict = await self._verdict(run, ws)
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

    # ── verdicts ──────────────────────────────────────────────────────────────────────────────
    async def _verdict(self, run: Run, ws: Workspace) -> Verdict | None:
        """The check decides when there is one. A run the harness itself failed is a failure.
        Otherwise the route's judge reads the output, if a judge is configured."""
        if run.check is not None:
            return Verdict(success=bool(run.check["pass"]), by="check", note=run.check["cmd"])
        if run.status != "ok":
            return Verdict(success=False, by="status", note=f"harness status {run.status}")
        route = self.registry.route()
        judge = make_judge(route, self.secrets, self.settings.jev_base_url, self.settings.jev_secret_name) if route else None
        if not judge:
            return None
        try:
            return await judge.judge(run, self.answer(run), self.produced_text(run, ws))
        except Exception as e:  # noqa: BLE001 — a judge that fails leaves the run unlabeled, never failed
            print(f"[judge] {run.id}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            return None

    def answer(self, run: Run) -> str:
        """What the harness said: the `answer` it reported, else the tail of its stdout."""
        a = run.output.get("answer")
        if isinstance(a, str) and a.strip():
            return a
        p = self.out_path(run.id)
        return p.read_text(errors="replace")[-8000:] if p.exists() else ""

    @staticmethod
    def produced_text(run: Run, ws: Workspace) -> dict[str, str]:
        out = {}
        for rel in run.files:
            try:
                p = ws.resolve(rel)
                out[rel] = p.read_text(errors="replace") if p.stat().st_size <= TEXT_FILE_BYTES else f"<{p.stat().st_size} bytes>"
            except (OSError, ValueError):
                out[rel] = "<unreadable>"
        return out

    def set_verdict(self, run_id: str, success: bool, note: str) -> Run | None:
        run = self.runs.get(run_id)
        if not run:
            return None
        run.verdict = Verdict(success=success, by="human", note=note)
        return self.runs.put(run.id, run)

    def cancel(self, run_id: str) -> bool:
        ex = self.live.get(run_id)
        if not ex:
            return False
        ex.cancel()
        return True
