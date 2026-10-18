"""Layer 6: turns, end to end, for any front end. A request is routed to a harness, resolved,
prepared and started; the turn then runs in the background, owned by the service: it runs to the
end and is recorded whether or not anyone is still following.

A conversation is a workspace and a session: a turn that continues an earlier one runs in its
workspace, resumes its session, and stays on its harness. A conversation runs one turn at a time.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from ..errors import Conflict, Invalid, NotFound
from ..harness import Request, Turn
from ..resources import JsonStore, Registry
from ..routing import ByName, Router
from ..workspace import Workspace
from .placement import Placement
from .records import Record, new_id
from .runs import Run


@dataclass(frozen=True)
class Ask:
    """A request for a turn, as any front end puts it."""
    model: str                                       # names the harness, for the router
    task: str
    instructions: str = ""
    files: dict[str, str] = field(default_factory=dict)
    previous_id: str | None = None                   # the turn this one continues
    metadata: dict[str, Any] = field(default_factory=dict)
    original: dict[str, Any] = field(default_factory=dict)     # the front end's own copy, kept on the record


class Service:
    def __init__(self, data: Path, registry: Registry, placement: Placement, router: Router | None = None):
        self.registry, self.placement, self.router = registry, placement, router or ByName()
        self.records: JsonStore[Record] = JsonStore(data / "records", lambda d: Record(**d))
        self.logs, self.workspaces = data / "logs", data / "workspaces"
        self.live: dict[str, Run] = {}
        self.busy: set[str] = set()                  # workspaces with a turn in flight

    async def start(self, ask: Ask) -> Run:
        """Check the request, prepare the turn and start it. Returns at once; the turn runs on."""
        previous = self._previous(ask.previous_id)
        route = self.router.route(ask.model, previous.harness if previous else None)
        resolved = self.registry.resolve(route.harness)
        rid = new_id()
        record = Record(id=rid, model=ask.model, harness=resolved.harness.name, provider=resolved.provider.name,
                        sandbox=resolved.sandbox.name, runtime=self.placement.name,
                        image=self.placement.image(resolved.sandbox),
                        workspace=previous.workspace if previous else str(self.workspaces / rid),
                        previous_id=ask.previous_id, session_id=previous.session_id if previous else "",
                        request=ask.original)
        if record.workspace in self.busy:
            raise Conflict(f"response {ask.previous_id} is part of a conversation that already has a turn in progress")
        self.busy.add(record.workspace)
        try:
            request = Request(ask.task, ask.instructions, route.model, ask.files, record.session_id, ask.metadata)
            turn = await Turn.start(self.placement.runtime(resolved), resolved.harness, resolved.provider, request,
                                    Path(record.workspace), resolved.scripts)
        except BaseException:
            self.busy.discard(record.workspace)
            raise
        record.base = turn.base
        run = Run(self.records.put(rid, record), turn)
        self.live[rid] = run
        run.task = asyncio.create_task(self._drive(run))
        return run

    def get(self, rid: str) -> Record:
        record = self.records.get(rid) if rid.startswith("resp_") and "/" not in rid else None
        if record is None:
            raise NotFound(f"no response {rid}")
        return record

    def list(self) -> list[Record]:
        return self.records.list()

    def cancel(self, rid: str) -> bool:
        """Stop a turn in flight; False if it isn't running."""
        run = self.live.get(rid)
        if run:
            run.cancel()
        return run is not None

    def workspace(self, rid: str) -> tuple[Record, Workspace]:
        record = self.get(rid)
        return record, Workspace(Path(record.workspace))

    def output_path(self, rid: str) -> Path:
        """What the harness printed on stdout, byte for byte."""
        return self.logs / f"{rid}.out"

    def log_path(self, rid: str) -> Path:
        """Everything else it printed: stderr."""
        return self.logs / f"{rid}.log"

    async def recover(self) -> None:
        """At startup: a restart ended every turn that was in flight. Close their records, and let
        the placement remove whatever they left behind."""
        for record in self.records.list():
            if record.status == "running":
                record.fail("server_restarted", "the server restarted while this turn was running")
                self.records.put(record.id, record)
        await self.placement.recover()

    def _previous(self, rid: str | None) -> Record | None:
        if not rid:
            return None
        try:
            return self.get(rid)
        except NotFound:
            raise Invalid(f"no response {rid}") from None

    async def _drive(self, run: Run) -> None:
        """Follow the turn to its end. Whatever happens, the record is finished and the conversation freed."""
        record = run.record
        try:
            await self._pump(run)
            record.finish(await run.turn.result())
        except Exception as e:                       # a bug, not the harness: the record still gets an end
            record.fail("internal_error", f"{type(e).__name__}: {e}")
        finally:
            self.records.put(record.id, record)
            self.busy.discard(record.workspace)
            self.live.pop(record.id, None)
            await run.close()

    async def _pump(self, run: Run) -> None:
        """Keep the harness's output byte for byte, and hand every event to followers as it comes."""
        files: dict[str, IO[bytes]] = {}
        try:
            async for event in run.turn.events():
                stdout = event.stream == "stdout"
                if event.stream not in files:
                    self.logs.mkdir(parents=True, exist_ok=True)
                    path = self.output_path(run.record.id) if stdout else self.log_path(run.record.id)
                    files[event.stream] = open(path, "ab")
                files[event.stream].write(event.data)
                files[event.stream].flush()
                await run.publish(event)
        finally:
            for f in files.values():
                f.close()
