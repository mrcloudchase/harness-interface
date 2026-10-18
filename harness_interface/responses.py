"""One response, end to end: resolve the three resources, prepare the workspace, run the harness
in its sandbox, record what it did. The HTTP layer only calls this.

A run belongs to the server, not to the request that started it. It runs to the end, and is
recorded, whether or not anyone is still listening; clients follow it while it runs.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

from .config import Settings
from .errors import ClientError, Conflict
from .models import Harness, HarnessInfo, Provider, Response, ResponseRequest, Sandbox
from .registry import Resources
from .runner import Prepared, prepare, read_output
from .runtime import Job, Process, Runtime
from .store import JsonStore
from .workspace import Workspace


def sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class Run:
    """A response in flight: its record, every line its harness has printed so far, on stdout
    ("output") or stderr ("log"), and how to stop it. Any number of clients can follow it."""

    def __init__(self, record: Response):
        self.record = record
        self.created = record.model_dump()           # the record as it was when the run began
        self.lines: list[tuple[str, str]] = []      # (kind, line), in the order they arrived
        self.proc: Process | None = None
        self.cancelled = False
        self.done = asyncio.Event()
        self._news = asyncio.Condition()
        self.task: asyncio.Task | None = None

    async def publish(self, kind: str, line: str) -> None:
        async with self._news:
            self.lines.append((kind, line))
            self._news.notify_all()

    async def close(self) -> None:
        async with self._news:
            self.done.set()
            self._news.notify_all()

    async def follow(self) -> AsyncIterator[tuple[str, str]]:
        """Every (kind, line), from the first, as it arrives, until the run is done."""
        seen = 0
        while True:
            async with self._news:
                await self._news.wait_for(lambda: len(self.lines) > seen or self.done.is_set())
                new, finished = self.lines[seen:], self.done.is_set()
            seen += len(new)
            for line in new:
                yield line
            if finished and seen == len(self.lines):
                return

    def cancel(self) -> None:
        """Stop the harness, or keep it from starting if its sandbox is still being set up."""
        self.cancelled = True
        if self.proc:
            self.proc.cancel()


class ResponseService:
    def __init__(self, settings: Settings, resources: Resources, runtime: Runtime, store: JsonStore[Response]):
        self.settings, self.resources, self.runtime, self.store = settings, resources, runtime, store
        self.live: dict[str, Run] = {}
        self.busy: set[str] = set()                  # workspaces with a run in flight: one at a time per conversation

    async def start(self, req: ResponseRequest) -> Run:
        """Check the request, prepare the workspace, and start the run. Returns at once; the
        harness runs on in the background."""
        harness, provider, sandbox = self._resolve(req)
        previous = self._previous(req, harness.name)
        record = Response(model=req.model, instructions=req.instructions, input=req.input,
                          previous_response_id=req.previous_response_id, metadata=req.metadata,
                          harness=HarnessInfo(name=harness.name, provider=provider.name, sandbox=sandbox.name,
                                              runtime=self.runtime.name, workspace="",
                                              session_id=previous.harness.session_id if previous else None))
        record.harness.workspace = previous.harness.workspace if previous else str(self.settings.workspaces / record.id)
        if record.harness.workspace in self.busy:
            raise Conflict(f"response {req.previous_response_id} is part of a conversation that already has a run in progress")
        self.busy.add(record.harness.workspace)
        try:
            ws = Workspace(Path(record.harness.workspace))
            prepared = await asyncio.to_thread(self._prepare, harness, provider, req, record, ws)
        except BaseException:
            self.busy.discard(record.harness.workspace)
            raise
        run = Run(self.store.put(record.id, record))
        self.live[record.id] = run
        run.task = asyncio.create_task(self._execute(run, harness, provider, sandbox, prepared, ws))
        return run

    def _resolve(self, req: ResponseRequest) -> tuple[Harness, Provider, Sandbox]:
        harness = self.resources.harnesses.get(req.harness)
        if not harness:
            raise ClientError(f"no harness '{req.harness}'")
        provider = self.resources.providers.get(harness.provider)
        if not provider:
            raise ClientError(f"harness '{harness.name}' names provider '{harness.provider}', which does not exist")
        sandbox = self.resources.sandbox(harness.sandbox)
        if not sandbox:
            raise ClientError(f"harness '{harness.name}' names sandbox '{harness.sandbox}', which does not exist")
        return harness, provider, sandbox

    def _previous(self, req: ResponseRequest, harness: str) -> Response | None:
        if not req.previous_response_id:
            return None
        previous = self.store.get(req.previous_response_id)
        if not previous:
            raise ClientError(f"no response {req.previous_response_id}")
        if previous.harness.name != harness:
            raise ClientError(f"response {previous.id} belongs to harness '{previous.harness.name}'; a conversation stays on its harness")
        return previous

    def _prepare(self, harness: Harness, provider: Provider, req: ResponseRequest, record: Response, ws: Workspace) -> Prepared:
        ws.init()
        prepared = prepare(harness, provider, req, record.harness.session_id, ws,
                           self.runtime.mounts(ws.path, self.resources.harness_dir(harness.name)))
        record.harness.base = ws.commit("prepare")   # baseline: only what the harness itself writes counts as produced
        return prepared

    async def _execute(self, run: Run, harness: Harness, provider: Provider, sandbox: Sandbox,
                       prepared: Prepared, ws: Workspace) -> None:
        """Image, sandbox, harness, record. Whatever happens, the record is finished and the
        conversation freed."""
        record, code, setup_error = run.record, None, None
        try:
            try:
                record.harness.image = await self.runtime.image(sandbox)
                if not run.cancelled:
                    run.proc = await self.runtime.start(Job(
                        id=record.id, prepared=prepared, workspace=ws.path, harness_dir=self.resources.harness_dir(harness.name),
                        image=record.harness.image, egress=[provider.host, *sandbox.egress]))
            except Exception as e:                   # the sandbox could not be set up; the harness never ran
                setup_error = str(e) or type(e).__name__
            if run.proc:
                if run.cancelled:                    # cancelled while the sandbox was being set up
                    run.proc.cancel()
                await self._pump(run)
                code = await run.proc.wait()
            proc = run.proc
            status = ("timeout" if proc and proc.timed_out else "cancelled" if run.cancelled
                      else "fail" if setup_error else None)
            output, files, deleted, commit = await asyncio.to_thread(self._collect, ws, record.id)
            record.harness.deleted, record.harness.commit = deleted, commit
            record.finish(status or str(output.get("status") or ("ok" if code == 0 else "fail")), code, output, files, setup_error)
        except Exception as e:                       # a bug, not the harness: the record still gets an end
            record.finish("fail", code, {}, [], f"{type(e).__name__}: {e}")
        finally:
            self.store.put(record.id, record)
            self.busy.discard(record.harness.workspace)
            self.live.pop(record.id, None)
            await run.close()

    async def _pump(self, run: Run) -> None:
        """Keep the harness's stdout and stderr byte for byte, and hand both to followers line
        by line, as they come: what a client sees is what the harness printed."""
        rid = run.record.id
        await asyncio.gather(self._pump_one(run, "output", self.settings.out_path(rid), stderr=False),
                             self._pump_one(run, "log", self.settings.log_path(rid), stderr=True))

    @staticmethod
    async def _pump_one(run: Run, kind: str, path: Path, stderr: bool) -> None:
        buf = b""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as out:
            async for chunk in run.proc.chunks(stderr=stderr):
                out.write(chunk)
                out.flush()
                *lines, buf = (buf + chunk).split(b"\n")
                for line in lines:
                    await run.publish(kind, line.decode(errors="replace"))
        if buf:
            await run.publish(kind, buf.decode(errors="replace"))

    @staticmethod
    def _collect(ws: Workspace, response_id: str) -> tuple[dict, list[str], list[str], str]:
        output, (files, deleted) = read_output(ws), ws.changes()
        return output, files, deleted, ws.commit(f"response {response_id}")

    async def stream(self, run: Run) -> AsyncIterator[bytes]:
        """Server-sent events in the Responses framing: created; then one `harness.output` per
        line of the harness's stdout and one `harness.log` per line of its stderr, as they come;
        completed. Leaving early stops the following, not the run."""
        yield sse("response.created", {"type": "response.created", "response": run.created})
        async for kind, line in run.follow():
            event = f"harness.{kind}"
            yield sse(event, {"type": event, "line": line})
        yield sse("response.completed", {"type": "response.completed", "response": run.record.model_dump()})

    def cancel(self, response_id: str) -> bool:
        run = self.live.get(response_id)
        if not run:
            return False
        run.cancel()
        return True

    async def recover(self) -> None:
        """At startup: a restart ended every run that was in flight. Close their records, and
        let the runtime remove whatever they left behind."""
        for record in self.store.list():
            if record.status == "in_progress":
                record.abandon()
                self.store.put(record.id, record)
        await self.runtime.recover()
