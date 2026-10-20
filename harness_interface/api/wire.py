"""Layer 6: the OpenAI Responses wire format, and the only module that knows it. A request becomes an
`Ask`; a response record and its artifacts become a response object, the Responses shape with one
`harness` object for everything that shape has no field for; a session becomes a session object; and
a session's events become server-sent events: `response.created`, `harness.stdout` and
`harness.stderr` (one per line), `harness.steer`, `session.interrupted` and `response.completed`.
A file's content is its text, or `{"base64": …}` when it isn't UTF-8; a key or token never appears."""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from ..sessions import Artifacts, Ask, ResponseRecord, Session, SessionEvent
from ..store import encode

DATA_URL = "data:"


class InputText(BaseModel):
    type: Literal["input_text"]
    text: str


class InputFile(BaseModel):
    type: Literal["input_file"]
    filename: str
    file_data: str                                   # the file's text, or a data:…;base64, URL

    @field_validator("file_data")
    @classmethod
    def _decodes(cls, v: str) -> str:
        content(v)
        return v


class Message(BaseModel):
    type: Literal["message"] = "message"
    role: Literal["user"]
    content: Union[str, list[Union[InputText, InputFile]]]


Item = Union[InputText, InputFile, Message]


def content(file_data: str) -> str | bytes:
    """A file's content from `file_data`: its text, or the bytes of a `data:…;base64,` URL."""
    if not file_data.startswith(DATA_URL):
        return file_data
    head, comma, data = file_data.partition(",")
    if not comma or not head.endswith(";base64"):
        raise ValueError("a data URL in file_data must be data:<type>;base64,<data>")
    try:
        return base64.b64decode(data, validate=True)
    except binascii.Error:
        raise ValueError("file_data is not valid base64") from None


def parts(given: str | list[Item]) -> list[InputText | InputFile]:
    if isinstance(given, str):
        return [InputText(type="input_text", text=given)]
    out: list[InputText | InputFile] = []
    for item in given:
        out += parts(item.content) if isinstance(item, Message) else [item]
    return out


class Input(BaseModel):
    input: Union[str, list[Item]]

    @property
    def task(self) -> str:
        return "\n".join(p.text for p in parts(self.input) if isinstance(p, InputText))

    @model_validator(mode="after")
    def _some_text(self) -> Input:
        if not self.task.strip():
            raise ValueError("input carries no text")
        return self


class ResponseRequest(Input):
    model: str
    instructions: str | None = None
    previous_response_id: str | None = None
    stream: bool = False
    metadata: dict[str, Any] | None = None

    def ask(self) -> Ask:
        files = {p.filename: content(p.file_data) for p in parts(self.input) if isinstance(p, InputFile)}
        return Ask(self.model, self.task, instructions=self.instructions or "", files=files,
                   previous=self.previous_response_id, metadata=self.metadata or {},
                   input=self.model_dump(mode="json")["input"])


class InterruptRequest(Input):
    instructions: str | None = None
    stream: bool = False

    @model_validator(mode="after")
    def _text_only(self) -> InterruptRequest:
        if any(isinstance(p, InputFile) for p in parts(self.input)):
            raise ValueError("an interrupt carries text only")
        return self


class StopRequest(BaseModel):
    timeout_s: float | None = Field(default=None, ge=0)


def usage(u: dict[str, Any]) -> dict[str, Any] | None:
    """The harness's usage in the Responses shape (all of it is under `harness.usage` too)."""
    if not u:
        return None
    count = {k: v if isinstance(v, int) and not isinstance(v, bool) else 0 for k, v in u.items()}
    i, o = count.get("input_tokens", 0), count.get("output_tokens", 0)
    return {"input_tokens": i, "output_tokens": o, "total_tokens": i + o,
            "input_tokens_details": {"cached_tokens": count.get("cache_read_tokens", 0)},
            "output_tokens_details": {"reasoning_tokens": count.get("reasoning_tokens", 0)}}


def files(changes: dict[str, bytes | None]) -> dict[str, Any]:
    return {p: None if c is None else encode(c) for p, c in changes.items()}


def response(r: ResponseRecord, a: Artifacts) -> dict[str, Any]:
    """A response in the Responses shape, with every artifact under `harness`."""
    text = [{"type": "message", "id": f"msg_{r.id.removeprefix('resp_')}", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": r.answer, "annotations": []}]}] if r.answer else []
    return {
        "id": r.id, "object": "response", "created_at": r.created_at, "status": r.status, "model": r.model,
        "instructions": r.request.get("instructions", ""), "input": r.request.get("input"),
        "previous_response_id": r.previous, "output": text, "usage": usage(r.usage),
        "error": r.error if r.status == "failed" else None,
        "incomplete_details": {"reason": "timeout"} if r.status == "incomplete" else None,
        "metadata": r.request.get("metadata") or {},
        "harness": {
            "session": r.session, "name": r.harness, "provider": r.provider, "exit_code": r.exit_code,
            "latency_s": r.latency_s, "usage": r.usage, "cost_usd": r.cost_usd, "resume": r.resume,
            "stdout": a.stdout.decode(errors="replace"), "stderr": a.stderr.decode(errors="replace"),
            "diff": a.diff, "changes": files(a.changes), "files": a.files, "home": files(a.home), "output": a.output,
            "steers": r.steers, "undelivered": r.undelivered, "stop": r.stop, "base": r.base, "commit": r.commit,
        },
    }


def session(s: Session, responses: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A session; with its responses, oldest first, when they are given."""
    out = {"id": s.id, "object": "session", "status": s.status, "harness": s.harness, "provider": s.provider,
           "model": s.model, "interrupt": s.interrupt, "resume": s.resume, "created_at": s.created_at,
           "updated_at": s.updated_at, "interrupts": s.interrupts}
    return out if responses is None else {**out, "responses": responses}


def sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


async def stream(events: AsyncIterator[SessionEvent],
                 shape: Callable[[ResponseRecord], Awaitable[dict[str, Any]]]) -> AsyncIterator[bytes]:
    """A session's events as server-sent events, output one line per event. Leaving stops the
    following, never the session."""
    partial: dict[tuple[str, str], bytes] = {}
    seq = 0

    def emit(event: str, **data: Any) -> bytes:
        nonlocal seq
        seq += 1
        return sse(event, {"type": event, "sequence_number": seq - 1, **data})

    def line(rid: str, kind: str, text: bytes) -> bytes:
        return emit(f"harness.{kind}", response=rid, line=text.decode(errors="replace"))

    async for e in events:
        if e.kind in ("stdout", "stderr"):
            *lines, partial[e.response, e.kind] = (partial.get((e.response, e.kind), b"") + e.data).split(b"\n")
            for text in lines:
                yield line(e.response, e.kind, text)
        elif e.kind == "steer":
            yield emit("harness.steer", response=e.response, input=e.data.decode(), at=e.at)
        elif e.kind == "interrupted":
            yield emit("session.interrupted", response=e.response, outcome=e.outcome, input=e.data.decode(),
                       at=e.at, **{"from": e.source})
        elif e.kind == "created":
            yield emit("response.created", response=await shape(e.record))
        else:
            for kind in ("stdout", "stderr"):
                if rest := partial.pop((e.response, kind), b""):
                    yield line(e.response, kind, rest)
            yield emit("response.completed", response=await shape(e.record))
