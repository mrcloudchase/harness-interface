"""Fan-out: the same request to every registered harness at once. The judge labels each run as
it finishes; the referee picks the winner among the delivered outputs. The contest record is the
only source of wins and losses."""
from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator

from .config import Settings
from .models import Contest, Run, RunRequest
from .registry import Registry
from .router import make_referee
from .runner import Execution
from .service import RunService
from .storage import JsonStore, SecretStore
from .workspace import Workspace

Launched = tuple[Run, Execution, Workspace]


class Arena:
    def __init__(self, settings: Settings, registry: Registry, secrets: SecretStore, service: RunService,
                 contests: JsonStore[Contest]):
        self.settings, self.registry, self.secrets, self.service, self.contests = settings, registry, secrets, service, contests

    def _referee(self):
        return make_referee(self.registry.route(), self.secrets, self.settings.jev_base_url, self.settings.jev_secret_name)

    async def start(self, request: RunRequest) -> tuple[Contest, list[Launched]]:
        self._referee()                                   # fail before anything runs if a contest cannot be settled
        harnesses = self.registry.list()
        if not harnesses:
            raise LookupError("no harnesses registered")
        contest = Contest(request=request)
        launched = []
        for h in harnesses:
            launched.append(await self.service.launch(request, h, contest=contest.id))
            contest.runs[h.name] = launched[-1][0].id
        return self.contests.put(contest.id, contest), launched

    async def stream(self, contest: Contest, launched: list[Launched]) -> AsyncIterator[bytes]:
        """NDJSON: one `{"harness", "line"}` per line of output as it arrives from any entrant,
        then the settled `{"contest"}` last. Every run is finished and judged even if the client leaves."""
        queue: asyncio.Queue = asyncio.Queue()
        tasks = [asyncio.create_task(self._pump(queue, *entry)) for entry in launched]
        try:
            open_ = len(tasks)
            while open_:
                item = await queue.get()
                if item is None:
                    open_ -= 1
                    continue
                yield json.dumps({"harness": item[0], "line": item[1]}).encode() + b"\n"
        finally:
            await asyncio.gather(*tasks)
            contest = await self.conclude(contest)
        yield json.dumps({"contest": contest.model_dump()}).encode() + b"\n"

    async def _pump(self, queue: asyncio.Queue, run: Run, execution: Execution, ws: Workspace) -> None:
        buf = b""
        async for chunk in self.service.stream(run, execution, ws):
            *lines, buf = (buf + chunk).split(b"\n")
            for line in lines:
                await queue.put((run.harness, line.decode(errors="replace")))
        if buf:
            await queue.put((run.harness, buf.decode(errors="replace")))
        await queue.put(None)

    async def finish(self, contest: Contest, launched: list[Launched]) -> Contest:
        async for _ in self.stream(contest, launched):
            pass
        return self.contests.get(contest.id) or contest

    async def conclude(self, contest: Contest) -> Contest:
        """Settle it: one deliverer wins outright, several go to the referee, none means no winner."""
        if contest.status != "running":
            return contest
        runs = {name: self.service.runs.get(rid) for name, rid in contest.runs.items()}
        delivered = {name: r for name, r in runs.items() if r and r.verdict and r.verdict.success}
        contest.status, contest.ended_at = "done", time.time()
        try:
            if len(delivered) == 1:
                contest.winner = next(iter(delivered))
            elif delivered:
                entrants = {name: (self.service.answer(r), self.service.produced_text(r, self.service.workspace(r)))
                            for name, r in delivered.items()}
                contest.winner, contest.answers = await self._referee().pick(contest.request, entrants)
        except Exception as e:  # noqa: BLE001 — a referee that fails voids the contest; nobody's record moves
            contest.status, contest.note = "void", f"referee failed: {type(e).__name__}: {str(e)[:200]}"
        if contest.winner:
            contest.session = runs[contest.winner].session
        return self.contests.put(contest.id, contest)
