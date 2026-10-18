"""Layer 7: the OpenAI Responses wire format, and its translation to and from the platform. The
only module that knows this format: a request becomes an Ask, a record becomes a Response, and a
run becomes server-sent events."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Literal

from pydantic import BaseModel, model_validator

from ..platform import Ask, Record, Run

STATUS = {"running": "in_progress", "completed": "completed", "failed": "failed",
          "timed_out": "incomplete", "cancelled": "cancelled"}


class InputText(BaseModel):
    type: Literal["input_text"]
    text: str


class InputFile(BaseModel):
    type: Literal["input_file"]
    filename: str
    file_data: str                                   # the file's text


class ResponseRequest(BaseModel):
    model: str                                       # "harness" or "harness/model"
    input: str | list[InputText | InputFile]
    instructions: str = ""
    previous_response_id: str | None = None
    stream: bool = False
    metadata: dict[str, Any] = {}

    @property
    def task(self) -> str:
        if isinstance(self.input, str):
            return self.input
        return "\n".join(i.text for i in self.input if isinstance(i, InputText))

    @property
    def files(self) -> dict[str, str]:
        if isinstance(self.input, str):
            return {}
        return {i.filename: i.file_data for i in self.input if isinstance(i, InputFile)}

    @model_validator(mode="after")
    def _some_task(self) -> ResponseRequest:
        if not self.task.strip():
            raise ValueError("input carries no text")
        return self

    def ask(self) -> Ask:
        return Ask(model=self.model, task=self.task, instructions=self.instructions, files=self.files,
                   previous_id=self.previous_response_id, metadata=self.metadata,
                   original=self.model_dump(include={"input", "instructions", "metadata"}))


def response(r: Record) -> dict[str, Any]:
    """A record in the Responses shape, plus one `harness` key for what that shape has no field for."""
    asked = r.request
    return {
        "id": r.id,
        "object": "response",
        "created_at": r.created_at,
        "status": STATUS[r.status],
        "model": r.model,
        "instructions": asked.get("instructions", ""),
        "input": asked.get("input", ""),
        "previous_response_id": r.previous_id,
        "output": ([{"type": "message", "role": "assistant", "status": "completed",
                     "content": [{"type": "output_text", "text": r.answer, "annotations": []}]}] if r.answer else []),
        "usage": r.usage,
        "error": {"code": r.error_code, "message": r.error} if r.status == "failed" else None,
        "incomplete_details": {"reason": "timeout"} if r.status == "timed_out" else None,
        "metadata": asked.get("metadata", {}),
        "harness": {
            "name": r.harness, "provider": r.provider, "sandbox": r.sandbox, "runtime": r.runtime,
            "image": r.image, "workspace": r.workspace, "session_id": r.session_id or None,
            "exit_code": r.exit_code, "latency_s": r.latency_s, "cost_usd": r.cost_usd,
            "files": r.files, "deleted": r.deleted, "base": r.base or None, "commit": r.commit or None,
        },
    }


def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


async def stream(run: Run) -> AsyncIterator[bytes]:
    """created; then one `harness.output` per line the harness printed on stdout and one
    `harness.log` per line on stderr, as they come; then completed. Leaving early stops the
    following, not the run."""
    yield sse("response.created", {"type": "response.created", "response": response(run.created)})
    partial: dict[str, bytes] = {}
    async for event in run.follow():
        kind = "output" if event.stream == "stdout" else "log"
        *lines, partial[kind] = (partial.get(kind, b"") + event.data).split(b"\n")
        for line in lines:
            yield _line(kind, line)
    for kind, rest in partial.items():
        if rest:
            yield _line(kind, rest)
    yield sse("response.completed", {"type": "response.completed", "response": response(run.record)})


def _line(kind: str, line: bytes) -> bytes:
    return sse(f"harness.{kind}", {"type": f"harness.{kind}", "line": line.decode(errors="replace")})
