"""One response, end to end: resolve the three resources, prepare the workspace, run the harness
in its sandbox, stream its output, write the record. The HTTP layer only calls this."""
from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

from .config import Settings
from .models import HarnessInfo, Response, ResponseRequest
from .registry import Resources
from .runner import Runner, read_output
from .sandbox import Job, Process, Sandbox
from .store import JsonStore
from .workspace import Workspace


def sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


class ResponseService:
    def __init__(self, settings: Settings, resources: Resources, sandbox: Sandbox, store: JsonStore[Response]):
        self.settings, self.resources, self.sandbox, self.store = settings, resources, sandbox, store
        self.live: dict[str, Process] = {}

    def log_path(self, response_id: str) -> Path:
        return self.settings.logs / f"{response_id}.log"

    def out_path(self, response_id: str) -> Path:
        return self.settings.logs / f"{response_id}.out"

    async def start(self, req: ResponseRequest) -> tuple[Response, Process, Workspace]:
        harness = self.resources.harnesses.get(req.harness)
        if not harness:
            raise LookupError(f"no harness '{req.harness}'")
        provider = self.resources.providers.get(harness.provider)
        if not provider:
            raise LookupError(f"harness '{harness.name}' names provider '{harness.provider}', which does not exist")
        spec = self.resources.sandbox(harness.sandbox)
        if not spec:
            raise LookupError(f"harness '{harness.name}' names sandbox '{harness.sandbox}', which does not exist")
        previous = self._previous(req, harness.name)

        record = Response(model=req.model, instructions=req.instructions, input=req.input,
                          previous_response_id=req.previous_response_id, metadata=req.metadata,
                          harness=HarnessInfo(name=harness.name, provider=provider.name, sandbox=spec.name,
                                              runtime=self.sandbox.runtime, workspace="",
                                              session_id=previous.harness.session_id if previous else None))
        record.harness.workspace = previous.harness.workspace if previous else str(self.settings.workspaces / record.id)

        ws = Workspace(Path(record.harness.workspace))
        ws.init()
        harness_dir = self.resources.harness_dir(harness.name)
        prepared = Runner.prepare(harness, provider, req, record.harness.session_id, ws,
                                  self.sandbox.mounts(ws.path, harness_dir))
        ws.commit("prepare")                         # baseline: only what the harness itself writes counts as produced
        record.harness.image = await self.sandbox.image(spec, harness.name)
        job = Job(id=record.id, harness=harness.name, prepared=prepared, workspace=ws.path, harness_dir=harness_dir,
                  log_path=self.log_path(record.id), spec=spec, egress=[provider.host, *spec.egress])
        proc = await self.sandbox.start(job)
        self.live[record.id] = proc
        return self.store.put(record.id, record), proc, ws

    def _previous(self, req: ResponseRequest, harness: str) -> Response | None:
        if not req.previous_response_id:
            return None
        previous = self.store.get(req.previous_response_id)
        if not previous:
            raise LookupError(f"no response {req.previous_response_id}")
        if previous.harness.name != harness:
            raise ValueError(f"response {previous.id} belongs to harness '{previous.harness.name}'; a conversation stays on its harness")
        return previous

    async def stream(self, record: Response, proc: Process, ws: Workspace) -> AsyncIterator[bytes]:
        """Server-sent events in the Responses framing: created, one `harness.output` per line of
        the harness's own stdout, completed. The run finishes and is recorded even if the client leaves."""
        yield sse("response.created", {"type": "response.created", "response": record.model_dump()})
        buf = b""
        try:
            async for chunk in proc.chunks():
                *lines, buf = (buf + chunk).split(b"\n")
                for line in lines:
                    yield sse("harness.output", {"type": "harness.output", "line": line.decode(errors="replace")})
        finally:
            if buf:
                yield sse("harness.output", {"type": "harness.output", "line": buf.decode(errors="replace")})
            record = await self.finish(record, proc, ws)
        yield sse("response.completed", {"type": "response.completed", "response": record.model_dump()})

    async def finish(self, record: Response, proc: Process, ws: Workspace) -> Response:
        code = await proc.wait()
        self.live.pop(record.id, None)
        output = read_output(ws)
        status = ("timeout" if proc.timed_out else "cancelled" if proc.cancelled
                  else str(output.get("status") or ("ok" if code == 0 else "fail")))
        record.finish(status, code, output, ws.changed())
        ws.commit(f"response {record.id}")
        return self.store.put(record.id, record)

    def cancel(self, response_id: str) -> bool:
        proc = self.live.get(response_id)
        if not proc:
            return False
        proc.cancel()
        return True
