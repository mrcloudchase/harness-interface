#!/usr/bin/env python3
"""The Responses wire end to end, in one file, around one template package: `foobarness/`.

    python3 prototype/foobarness_wire.py

What it shows, in order:

1. A client's request in the OpenAI Responses schema. `parse_request` resolves it into the fixed
   subset a harness gets (prompt, files, instructions, continuation, model, reasoning effort, MCP
   tools) and refuses, with the standard error shape, anything the package's manifest does not accept.
2. `stage` writes that subset where the package reads it: the files into the workspace, the prompt
   and `request.json` into the run directory. This is the only thing a package sees of the request.
3. `run_turn` is the template: the common runner every package shares. It runs the adapter's
   configure.sh (seeds become the CLI's config), then run.sh (the CLI, its native events relayed
   live) piped through items.py (the package's filter: native events become Responses items).
4. `response_object` and `events` put the items back on the wire: the non-streaming response
   object, and the standard event stream with the same items and the message's deltas.

Nothing here is Docker, the gateway or the store: the turn runs as a process in a temporary
directory, with a fake provider URL and token, so the mapping is the whole subject.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

HERE = Path(__file__).resolve().parent
PACKAGE = HERE / "foobarness"


class Refused(Exception):
    """A request the harness cannot take; `body` is the Responses API's error shape, HTTP 400."""

    def __init__(self, message: str, param: str, code: str = "unsupported_parameter"):
        super().__init__(message)
        self.body = {"error": {"type": "invalid_request_error", "code": code, "message": message, "param": param}}


# 1. the request, as a client sends it, resolved into what a harness gets
def parse_request(body: dict[str, Any], manifest: dict[str, Any], previous_turn: Turn | None) -> dict[str, Any]:
    accepts = manifest["accepts"]
    parts = str(body.get("model", "")).split("/", 2)
    harness, provider, model = (parts[0], "", "") if len(parts) == 1 else (parts[0], parts[1], parts[2])
    if not harness:
        raise Refused("model is a harness name, or harness/provider/model", "model", "invalid_value")
    prompt, files = [], {}
    given = body.get("input", "")
    for item in [{"type": "input_text", "text": given}] if isinstance(given, str) else given:
        for part in item.get("content", [item]) if item.get("type") == "message" else [item]:
            if part.get("type") == "input_text":
                prompt.append(part["text"])
            elif part.get("type") == "input_file":
                if not accepts["input_file"]:
                    raise Refused(f"{harness} takes no files", "input")
                data = part["file_data"]
                files[part["filename"]] = base64.b64decode(data.split(",", 1)[1]) if data.startswith("data:") else data.encode()
    if not "".join(prompt).strip():
        raise Refused("input carries no text", "input", "invalid_value")
    if body.get("instructions") and not accepts["instructions"]:
        raise Refused(f"{harness} takes no instructions", "instructions")
    if body.get("previous_response_id") and not accepts["previous_response_id"]:
        raise Refused(f"{harness} cannot continue a session", "previous_response_id")
    mcp = []
    for tool in body.get("tools") or []:
        if tool.get("type") != "mcp" or "mcp" not in accepts["tools"]:
            raise Refused(f"{harness} runs its own tools; a tool of type {tool.get('type')!r} cannot be given to it", "tools")
        mcp.append({"name": tool["server_label"], "url": tool["server_url"]})
    effort = (body.get("reasoning") or {}).get("effort")
    if effort and effort not in accepts["reasoning_effort"]:
        raise Refused(f"reasoning.effort is one of {', '.join(accepts['reasoning_effort'])}", "reasoning.effort", "invalid_value")
    for knob in ("temperature", "top_p", "max_output_tokens"):
        if knob in body and not accepts["sampling"]:
            raise Refused(f"{harness} does not take {knob}: its CLI decides", knob)
    if (body.get("text") or {}).get("format", {}).get("type", "text") != "text" and not accepts["text_format"]:
        raise Refused(f"{harness} returns text; it takes no output format", "text.format")
    return {"harness": harness, "provider": provider or manifest["defaults"]["provider"], "model": model or manifest["defaults"]["model"],
            "prompt": "\n".join(prompt), "files": files, "instructions": body.get("instructions") or "",
            "resume": bool(body.get("previous_response_id")), "reasoning_effort": effort or "medium", "mcp_servers": mcp,
            "metadata": body.get("metadata") or {}, "store": body.get("store", True)}


# 2. staged: what the package finds on disk
def stage(session: Session, ask: dict[str, Any]) -> dict[str, Any]:
    for rel, data in ask["files"].items():
        (session.workspace / rel).parent.mkdir(parents=True, exist_ok=True)
        (session.workspace / rel).write_bytes(data)
    request = {"turn": session.turn + 1, "resume": ask["resume"], "model": ask["model"], "instructions": ask["instructions"],
               "reasoning_effort": ask["reasoning_effort"], "mcp_servers": ask["mcp_servers"], "files": sorted(ask["files"])}
    (session.run / "prompt").write_text(ask["prompt"])
    (session.run / "request.json").write_text(json.dumps(request, indent=1))
    return request


@dataclass
class Session:
    root: Path
    id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex}")
    turn: int = 0

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def run(self) -> Path:
        return self.root / "run"

    @property
    def home(self) -> Path:
        return self.root / "home"


@dataclass
class Turn:
    """A turn as the platform keeps it: the items the package reported, in order, the message
    assembled from the deltas, and how it ended."""
    id: str
    session: str
    harness: str
    provider: str
    model: str
    turn: int
    previous: str | None
    instructions: str
    metadata: dict[str, str]
    store: bool
    created: float = field(default_factory=time.time)
    items: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    status: str = "in_progress"
    exit_code: int | None = None
    native: str = ""

    @property
    def message_id(self) -> str:
        return f"msg_{self.id[5:29]}"

    def message(self, done: bool) -> dict[str, Any]:
        return {"type": "message", "id": self.message_id, "status": "completed" if done else "in_progress", "role": "assistant",
                "content": [{"type": "output_text", "text": self.text, "annotations": []}]}


# 3. the template: install once, then configure -> run | items, relayed as it happens
def install(tools: Path) -> None:
    env = {**os.environ, "HG_TOOLS": str(tools), "HG_HARNESS_DIR": str(PACKAGE)}
    subprocess.run(["bash", str(PACKAGE / "install.sh")], env=env, check=True, capture_output=True)


def run_turn(session: Session, turn: Turn, ask: dict[str, Any], tools: Path) -> Iterator[tuple[str, Any]]:
    """Yields ("native", line) for every line the CLI printed, ("item", item) and ("delta", text) as
    the filter reports them, then ("end", exit_code)."""
    for d in (session.workspace, session.run, session.home):
        d.mkdir(parents=True, exist_ok=True)
    stage(session, ask)
    env = {"PATH": f"{tools}/bin:{os.environ['PATH']}", "HOME": str(session.home), "HG_WORKSPACE": str(session.workspace),
           "HG_DIR": str(session.run), "HG_REQUEST": str(session.run / "request.json"), "HG_HARNESS_DIR": str(PACKAGE),
           "HG_TOOLS": str(tools), "HG_SESSION": session.id, "HG_RESPONSE": turn.id, "HG_TURN": str(turn.turn),
           "HG_MODEL": ask["model"], "HG_INSTRUCTIONS": ask["instructions"], "HG_PROVIDER_URL": "http://hg-provider:8080",
           "FOOBAR_API_KEY": "sk-hg-session-token", "FOOBAR_BASE_URL": "http://hg-provider:8080"}
    subprocess.run(["bash", str(PACKAGE / "adapter" / "configure.sh")], env=env, check=True)
    native = session.run / "native.jsonl"
    pipeline = f'bash "$HG_HARNESS_DIR/adapter/run.sh" | tee "{native}" | python3 "$HG_HARNESS_DIR/adapter/items.py"'
    proc = subprocess.Popen(["bash", "-o", "pipefail", "-c", pipeline], env=env, stdout=subprocess.PIPE, text=True)
    seen = 0
    for line in proc.stdout:
        lines = native.read_text().splitlines()
        for raw in lines[seen:]:
            yield "native", raw
        seen = len(lines)
        report = json.loads(line)
        if "item" in report:
            turn.items.append(report["item"])
            yield "item", report["item"]
        else:
            turn.text += report["delta"]
            yield "delta", report["delta"]
    code = proc.wait()
    turn.native = native.read_text()
    turn.exit_code, turn.status = code, "completed" if code == 0 else "failed"
    session.turn = turn.turn
    yield "end", code


# 4. back on the wire: the response object, and the stream
def response_object(t: Turn) -> dict[str, Any]:
    done = t.status != "in_progress"
    return {"id": t.id, "object": "response", "created_at": int(t.created), "status": t.status,
            "error": {"code": "exit_status", "message": f"the package exited {t.exit_code}"} if t.status == "failed" else None,
            "incomplete_details": None, "instructions": t.instructions or None, "max_output_tokens": None,
            "model": f"{t.harness}/{t.provider}/{t.model}", "output": [*t.items, *([t.message(True)] if done or t.text else [])],
            "parallel_tool_calls": False, "previous_response_id": t.previous, "reasoning": {"effort": None, "summary": None},
            "store": t.store, "temperature": None, "text": {"format": {"type": "text"}}, "tool_choice": "none", "tools": [],
            "top_p": None, "truncation": "disabled", "usage": None, "user": None,
            "metadata": {**t.metadata, "session_id": t.session, "harness": t.harness, "turn": str(t.turn)}}


def output_text(response: dict[str, Any]) -> str:
    """What an SDK's `response.output_text` returns: every output_text part, joined."""
    return "".join(p["text"] for item in response["output"] if item["type"] == "message" for p in item["content"] if p["type"] == "output_text")


def events(t: Turn, relay: Iterator[tuple[str, Any]]) -> Iterator[str]:
    """The standard stream: each item added and done as it arrives; the message opened on its first
    delta, closed before the next item or at the end; the final event with the whole response."""
    n = -1

    def event(kind: str, **data: Any) -> str:
        nonlocal n
        n += 1
        return f"event: {kind}\ndata: {json.dumps({'type': kind, 'sequence_number': n, **data})}\n\n"

    index, message_open = 0, False

    def close_message():
        nonlocal index, message_open
        yield event("response.output_text.done", item_id=t.message_id, output_index=index, content_index=0, text=t.text)
        yield event("response.content_part.done", item_id=t.message_id, output_index=index, content_index=0,
                    part={"type": "output_text", "text": t.text, "annotations": []})
        yield event("response.output_item.done", output_index=index, item=t.message(True))
        index, message_open = index + 1, False

    yield event("response.created", response=response_object(t))
    yield event("response.in_progress", response=response_object(t))
    for kind, data in relay:
        if kind == "item":
            if message_open:
                yield from close_message()
            skeleton = {**data, "status": "in_progress", **({"arguments": ""} if data["type"] in ("function_call", "mcp_call") else {})}
            yield event("response.output_item.added", output_index=index, item=skeleton)
            if data["type"] in ("function_call", "mcp_call"):
                stem = "response.function_call_arguments" if data["type"] == "function_call" else "response.mcp_call_arguments"
                yield event(f"{stem}.delta", item_id=data["id"], output_index=index, delta=data["arguments"])
                yield event(f"{stem}.done", item_id=data["id"], output_index=index, arguments=data["arguments"])
            yield event("response.output_item.done", output_index=index, item=data)
            index += 1
        elif kind == "delta":
            if not message_open:
                message_open = True
                yield event("response.output_item.added", output_index=index, item={**t.message(False), "content": []})
                yield event("response.content_part.added", item_id=t.message_id, output_index=index, content_index=0,
                            part={"type": "output_text", "text": "", "annotations": []})
            yield event("response.output_text.delta", item_id=t.message_id, output_index=index, content_index=0, delta=data)
        elif kind == "end":
            if message_open:
                yield from close_message()
            yield event("response.completed" if t.status == "completed" else "response.failed", response=response_object(t))


# the demo
def show(title: str, body: Any = None) -> None:
    print(f"\n\033[1m── {title}\033[0m")
    if body is not None:
        print(json.dumps(body, indent=2) if not isinstance(body, str) else body)


def main() -> None:
    manifest = json.loads((PACKAGE / "harness.json").read_text())
    root = Path(tempfile.mkdtemp(prefix="foobarness-"))
    tools = root / "tools"
    install(tools)
    turns: dict[str, tuple[Session, Turn]] = {}
    show("the package's manifest: what it accepts of a request", manifest["accepts"])

    def create(body: dict[str, Any]) -> Turn:
        prev = turns.get(body.get("previous_response_id") or "")
        ask = parse_request(body, manifest, prev[1] if prev else None)
        session = prev[0] if prev else Session(root / "sessions" / uuid.uuid4().hex[:8])
        t = Turn(f"resp_{uuid.uuid4().hex}", session.id, ask["harness"], ask["provider"], ask["model"], session.turn + 1,
                 body.get("previous_response_id"), ask["instructions"], ask["metadata"], ask["store"])
        turns[t.id] = (session, t)
        t.relay = run_turn(session, t, ask, tools)   # type: ignore[attr-defined]
        return t

    # A: a non-streaming request with instructions, an MCP tool of its own, a reasoning effort and metadata
    request_a = {"model": "foobarness", "instructions": "Answer in one sentence.",
                 "input": "Create hello.py that prints hello and run it",
                 "tools": [{"type": "mcp", "server_label": "search", "server_url": "https://mcp.example.com/search"}],
                 "reasoning": {"effort": "high"}, "metadata": {"ticket": "HG-12"}}
    show("A. the request, as a client sends it (POST /v1/responses)", request_a)
    a = create(request_a)
    native: list[str] = []
    for kind, data in a.relay:                        # type: ignore[attr-defined]
        if kind == "native":
            native.append(data)
    session = turns[a.id][0]
    show("A. what the harness got: $HG_REQUEST, written by the template", json.loads((session.run / "request.json").read_text()))
    show("A. what the adapter made of the seeds and the request: foobar's own config", json.loads((session.home / ".foobar" / "config.json").read_text()))
    show("A. the CLI's native events (foobar's shapes, relayed live, kept as the capture)", "\n".join(native))
    show("A. the items the package's filter reported", a.items)
    response_a = response_object(a)
    show("A. the response object, back on the wire", response_a)
    show("A. response.output_text, as an SDK reads it", output_text(response_a))
    show("A. the workspace after the turn", sorted(p.name for p in session.workspace.iterdir()))

    # B: a streamed continuation, with a file attached
    request_b = {"model": "foobarness", "previous_response_id": a.id, "stream": True,
                 "input": [{"type": "message", "role": "user", "content": [
                     {"type": "input_text", "text": "Run it again and tell me what files are here."},
                     {"type": "input_file", "filename": "notes.txt", "file_data": "data:text/plain;base64," + base64.b64encode(b"remember the milk\n").decode()}]}]}
    show("B. a continuation, streamed, with a file (POST /v1/responses)", request_b)
    b = create(request_b)
    show("B. the event stream (text/event-stream), as it arrives")
    for sse in events(b, b.relay):                    # type: ignore[attr-defined]
        kind, data = sse.split("\n")[0][7:], json.loads(sse.split("\n")[1][6:])
        if "response" in data:
            data["response"] = {"id": data["response"]["id"], "status": data["response"]["status"], "output": f"{len(data['response']['output'])} items"}
        print(f"  {kind:<40} {json.dumps({k: v for k, v in data.items() if k not in ('type', 'sequence_number')})[:150]}")
    show("B. response.output_text at the end", output_text(response_object(b)))

    # C: what the manifest refuses
    for request_c in ({"model": "foobarness", "input": "x", "tools": [{"type": "function", "name": "run", "parameters": {}}]},
                      {"model": "foobarness", "input": "x", "temperature": 0.2},
                      {"model": "foobarness", "input": "x", "reasoning": {"effort": "max"}}):
        try:
            parse_request(request_c, manifest, None)
        except Refused as e:
            show(f"C. refused, 400: {json.dumps({k: v for k, v in request_c.items() if k not in ('model', 'input')})}", e.body)
    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
