"""Layer 6: the OpenAI Responses wire format, and the only module that knows it. A request becomes an
`Ask`; a record becomes a response object whose `output` is two messages, stdout then stderr, and
whose status is the exit code's; a running record becomes the standard event stream. Nothing of
the harness's output is read, dropped or reshaped: the bytes it wrote are the text."""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..sessions import STREAMS, Ask, Record, SessionRecord
from ..store import Member

DATA_URL = "data:"
OVERRIDES = ("sandbox", "provider", "model")       # metadata keys that override harness.json's defaults


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
    role: Literal["user", "system", "developer"]
    content: Union[str, list[Union[InputText, InputFile]]]


Item = Union[InputText, InputFile, Message]


def content(file_data: str) -> bytes:
    """A file's content from `file_data`: its text, or the bytes of a `data:…;base64,` URL."""
    if not file_data.startswith(DATA_URL):
        return file_data.encode()
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
    model_config = ConfigDict(extra="ignore")       # a Responses client's other fields are not ours to refuse
    input: Union[str, list[Item]]

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in parts(self.input) if isinstance(p, InputText))

    @model_validator(mode="after")
    def _some_text(self) -> Input:
        if not self.text.strip():
            raise ValueError("input carries no text")
        return self


class ResponseRequest(Input):
    model: str                                       # the harness's name
    instructions: str | None = None
    previous_response_id: str | None = None
    store: bool = True
    stream: bool = False
    background: bool = False
    metadata: dict[str, str] | None = None

    def ask(self, who: Member) -> Ask:
        meta = self.metadata or {}
        files = {p.filename: content(p.file_data) for p in parts(self.input) if isinstance(p, InputFile)}
        return Ask(who.org, who.name, self.model, self.text, instructions=self.instructions or "", files=files,
                   sandbox=meta.get("sandbox", ""), provider=meta.get("provider", ""), model=meta.get("model", ""),
                   previous=self.previous_response_id, store=self.store, metadata=meta,
                   body=self.model_dump(mode="json", exclude_none=True))


class InterruptRequest(Input):
    @model_validator(mode="after")
    def _text_only(self) -> InterruptRequest:
        if any(isinstance(p, InputFile) for p in parts(self.input)):
            raise ValueError("an interrupt carries text only")
        return self


def item_id(rid: str, stream: str) -> str:
    return f"msg_{rid[5:29]}{STREAMS.index(stream)}"


def message(rid: str, stream: str, text: str, done: bool) -> dict[str, Any]:
    return {"type": "message", "id": item_id(rid, stream), "role": "assistant",
            "status": "completed" if done else "in_progress",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def response(r: Record) -> dict[str, Any]:
    """The response object: the standard shape, the harness's two streams as its two messages."""
    done = r.status != "in_progress"
    error = {"code": "server_error" if r.exit_code is None else "exit_status", "message": r.error} \
        if r.status == "failed" else None
    incomplete = {"reason": "timeout"} if r.status == "incomplete" else None
    meta = {**r.metadata, "session_id": r.session, "harness": r.harness, "version": r.version, "sandbox": r.sandbox,
            "provider": r.provider, "model": r.model, "turn": str(r.turn),
            **({"exit_code": str(r.exit_code)} if r.exit_code is not None else {})}
    return {"id": r.id, "object": "response", "created_at": int(r.created), "status": r.status, "model": r.harness,
            "previous_response_id": r.previous, "store": r.store, "error": error, "incomplete_details": incomplete,
            "instructions": None, "metadata": meta,
            "output": [message(r.id, s, getattr(r, s), done) for s in STREAMS],
            "usage": None, "parallel_tool_calls": False, "tool_choice": "none", "tools": [],
            "temperature": None, "top_p": None, "truncation": "disabled", "text": {"format": {"type": "text"}}}


def session(s: SessionRecord, running: bool) -> dict[str, Any]:
    return {"id": s.id, "object": "session", "harness": s.harness, "version": s.version, "member": s.member,
            "created_at": int(s.created), "stored": s.stored, "status": "running" if running else "idle",
            "responses": list(s.responses)}


FINAL = {"completed": "response.completed", "failed": "response.failed", "incomplete": "response.incomplete",
         "cancelled": "response.incomplete"}


async def stream(r: Record, output: AsyncIterator[tuple[str, str]],
                 ended: Callable[[], Awaitable[Record]]) -> AsyncIterator[str]:
    """The standard event stream: the response created, its two items added, every chunk a delta on
    its item, the items done, then the final event with the response as it ended."""
    n = 0
    texts = {s: "" for s in STREAMS}

    def event(kind: str, **data: Any) -> str:
        nonlocal n
        n += 1
        return f"event: {kind}\ndata: {json.dumps({'type': kind, 'sequence_number': n, **data})}\n\n"

    partial = response(r)
    yield event("response.created", response=partial)
    yield event("response.in_progress", response=partial)
    for i, s in enumerate(STREAMS):
        yield event("response.output_item.added", output_index=i, item=message(r.id, s, "", False))
        yield event("response.content_part.added", item_id=item_id(r.id, s), output_index=i, content_index=0,
                    part={"type": "output_text", "text": "", "annotations": []})
    async for s, text in output:
        texts[s] += text
        yield event("response.output_text.delta", item_id=item_id(r.id, s), output_index=STREAMS.index(s),
                    content_index=0, delta=text)
    final = await ended()
    for i, s in enumerate(STREAMS):
        yield event("response.output_text.done", item_id=item_id(r.id, s), output_index=i, content_index=0,
                    text=getattr(final, s))
        yield event("response.content_part.done", item_id=item_id(r.id, s), output_index=i, content_index=0,
                    part={"type": "output_text", "text": getattr(final, s), "annotations": []})
        yield event("response.output_item.done", output_index=i, item=message(final.id, s, getattr(final, s), True))
    yield event(FINAL.get(final.status, "response.failed"), response=response(final))
