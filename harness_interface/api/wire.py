"""Layer 6: the OpenAI Responses wire format, and the only module that knows it. A request becomes an
`Ask`: its `model` is a harness name, or `harness/provider/model` naming all three; a record becomes
a response object whose `model` is the path that ran, whose one output message is what the package
returned, and whose status is the package's exit code; a running record becomes the standard event
stream, its deltas request.sh's live stdout. Nothing of the package's output is read or reshaped."""
from __future__ import annotations

import base64
import binascii
import json
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Union

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ..sessions import Ask, Record, SessionRecord
from ..store import Member

DATA_URL = "data:"
MODEL_FORM = "model is a harness name, or harness/provider/model"


def parse_model(model: str) -> tuple[str, str, str]:
    """`model` as (harness, provider, model): a bare harness name takes the package's defaults; the
    full path names all three, the model last so it may hold slashes of its own."""
    parts = model.split("/", 2)
    if len(parts) == 1 and parts[0]:
        return parts[0], "", ""
    if len(parts) == 3 and all(parts[:2]):
        return parts[0], parts[1], parts[2]
    raise ValueError(MODEL_FORM)


def model_path(harness: str, provider: str, model: str) -> str:
    return f"{harness}/{provider}/{model}"


class InputText(BaseModel):
    type: Literal["input_text"]
    text: str


class InputFile(BaseModel):
    type: Literal["input_file"]
    filename: str
    file_data: str

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
    model_config = ConfigDict(extra="ignore")
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
    model: str
    instructions: str | None = None
    previous_response_id: str | None = None
    store: bool = True
    stream: bool = False
    background: bool = False
    metadata: dict[str, str] | None = None

    @field_validator("model")
    @classmethod
    def _well_formed(cls, v: str) -> str:
        parse_model(v)
        return v

    def ask(self, who: Member) -> Ask:
        harness, provider, model = parse_model(self.model)
        files = {p.filename: content(p.file_data) for p in parts(self.input) if isinstance(p, InputFile)}
        body = self.model_dump(mode="json", exclude_none=True)
        if files:                                    # the trace keeps the files' names and sizes, not their bytes
            body["input"] = [{"type": "input_text", "text": self.text}, *({"type": "input_file", "filename": n, "bytes": len(b)} for n, b in files.items())]
        return Ask(who.tenant, who.name, harness, self.text, instructions=self.instructions or "", files=files,
                   provider=provider, model=model, previous=self.previous_response_id, store=self.store,
                   metadata=self.metadata or {}, body=body)


class InterruptRequest(Input):
    @model_validator(mode="after")
    def _text_only(self) -> InterruptRequest:
        if any(isinstance(p, InputFile) for p in parts(self.input)):
            raise ValueError("an interrupt carries text only")
        return self


def item_id(rid: str) -> str:
    return f"msg_{rid[5:29]}"


def message(rid: str, text: str, done: bool) -> dict[str, Any]:
    return {"type": "message", "id": item_id(rid), "role": "assistant", "status": "completed" if done else "in_progress",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}


def response(r: Record) -> dict[str, Any]:
    """The response object: the standard shape, the package's return as its one message."""
    done = r.final
    error = {"code": "server_error" if r.exit_code is None else "exit_status", "message": r.error} if r.status == "failed" else None
    incomplete = {"reason": "timeout"} if r.status == "incomplete" else None
    meta = {**r.metadata, "session_id": r.session, "harness": r.harness, "version": r.version, "turn": str(r.turn),
            **({"exit_code": str(r.exit_code)} if r.exit_code is not None else {}), **({"truncated": "true"} if r.truncated else {})}
    return {"id": r.id, "object": "response", "created_at": int(r.created), "status": "in_progress" if not done else r.status,
            "model": model_path(r.harness, r.provider, r.model), "previous_response_id": r.previous, "store": r.store,
            "error": error, "incomplete_details": incomplete, "instructions": r.instructions or None, "metadata": meta,
            "output": [message(r.id, r.output, done)], "usage": None, "parallel_tool_calls": False, "tool_choice": "none",
            "tools": [], "temperature": None, "top_p": None, "truncation": "disabled", "text": {"format": {"type": "text"}}}


def record_detail(r: Record) -> dict[str, Any]:
    """The response plus the raw streams, for a member who wants what request.sh printed."""
    return {**response(r), "stdout": r.stdout, "stderr": r.stderr, "worker": r.worker, "started": r.started, "ended": r.ended}


def session(s: SessionRecord) -> dict[str, Any]:
    return {"id": s.id, "object": "session", "harness": s.harness, "version": s.version, "member": s.member,
            "created_at": int(s.created), "stored": s.stored, "status": "running" if s.running else "idle",
            "responses": list(s.responses)}


FINAL = {"completed": "response.completed", "failed": "response.failed", "incomplete": "response.incomplete",
         "cancelled": "response.incomplete"}


async def stream(r: Record, output: AsyncIterator[tuple[str, str]], ended: Callable[[], Awaitable[Record]]) -> AsyncIterator[str]:
    """The standard event stream: the response created, its item added, every stdout chunk a delta,
    the item done with the package's return, then the final event with the response as it ended."""
    n = 0

    def event(kind: str, **data: Any) -> str:
        nonlocal n
        n += 1
        return f"event: {kind}\ndata: {json.dumps({'type': kind, 'sequence_number': n, **data})}\n\n"

    partial = response(r)
    yield event("response.created", response=partial)
    yield event("response.in_progress", response=partial)
    yield event("response.output_item.added", output_index=0, item=message(r.id, "", False))
    yield event("response.content_part.added", item_id=item_id(r.id), output_index=0, content_index=0,
                part={"type": "output_text", "text": "", "annotations": []})
    async for s, text in output:
        if s == "stdout":
            yield event("response.output_text.delta", item_id=item_id(r.id), output_index=0, content_index=0, delta=text)
    final = await ended()
    yield event("response.output_text.done", item_id=item_id(r.id), output_index=0, content_index=0, text=final.output)
    yield event("response.content_part.done", item_id=item_id(r.id), output_index=0, content_index=0,
                part={"type": "output_text", "text": final.output, "annotations": []})
    yield event("response.output_item.done", output_index=0, item=message(final.id, final.output, True))
    yield event(FINAL.get(final.status, "response.failed"), response=response(final))
