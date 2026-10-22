"""Layer 6: a request becomes an Ask; a record becomes the standard response object; the stream is
the standard events in order; nothing of the output is reshaped."""
import asyncio
import base64
import json

import pytest
from pydantic import ValidationError

from harness_interface.api import wire
from harness_interface.sessions import Record
from harness_interface.store import Member

DEV = Member("acme", "dev", "member", 0)


def record(**kw) -> Record:
    base = dict(id="resp_" + "a" * 32, session="sess_" + "b" * 32, tenant="acme", member="dev", harness="cc",
                version="0" * 16, provider="prov", model="m1", turn=1, created=1700000000.5, previous=None, store=True,
                metadata={"team": "x"})
    return Record(**{**base, **kw})


def test_request_to_ask():
    req = wire.ResponseRequest(model="cc", input="do it", instructions="care", previous_response_id="resp_1",
                               store=False, metadata={"team": "x"}, temperature=0.2, tools=[])
    a = req.ask(DEV)
    assert (a.tenant, a.member, a.harness, a.prompt, a.instructions) == ("acme", "dev", "cc", "do it", "care")
    assert (a.provider, a.model, a.previous, a.store) == ("", "", "resp_1", False)
    assert a.body["input"] == "do it" and "temperature" not in a.body and a.metadata["team"] == "x"
    a = wire.ResponseRequest(model="cc/prov/vendor/m2", input="x").ask(DEV)
    assert (a.harness, a.provider, a.model) == ("cc", "prov", "vendor/m2")
    assert wire.ResponseRequest(model="cc/prov/", input="x").ask(DEV).model == ""
    for bad in ("", "cc/prov", "/cc/prov/m", "cc//m"):
        with pytest.raises(ValidationError):
            wire.ResponseRequest(model=bad, input="x")


def test_request_files_and_messages():
    data = base64.b64encode(b"\x00\x01").decode()
    req = wire.ResponseRequest(model="cc", input=[
        {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "read these"},
            {"type": "input_file", "filename": "a.txt", "file_data": "plain text"},
            {"type": "input_file", "filename": "b.bin", "file_data": f"data:application/octet-stream;base64,{data}"}]},
        {"type": "input_text", "text": "then answer"}])
    a = req.ask(DEV)
    assert a.prompt == "read these\nthen answer" and a.files == {"a.txt": b"plain text", "b.bin": b"\x00\x01"}
    assert a.body["input"][1] == {"type": "input_file", "filename": "a.txt", "bytes": 10}   # the trace keeps names and sizes
    with pytest.raises(ValidationError):
        wire.ResponseRequest(model="cc", input=[{"type": "input_file", "filename": "x", "file_data": "d"}])
    with pytest.raises(ValidationError):
        wire.InterruptRequest(input=[{"type": "input_file", "filename": "x", "file_data": "d"}])


def test_response_object():
    r = wire.response(record(status="completed", output="the answer", stdout="raw\n", exit_code=0))
    assert r["object"] == "response" and r["status"] == "completed" and r["model"] == "cc/prov/m1" and r["error"] is None
    assert [m["content"][0]["text"] for m in r["output"]] == ["the answer"]
    assert r["metadata"] == {"team": "x", "session_id": "sess_" + "b" * 32, "harness": "cc", "version": "0" * 16, "turn": "1", "exit_code": "0"}
    assert wire.record_detail(record(status="completed", stdout="raw\n"))["stdout"] == "raw\n"
    failed = wire.response(record(status="failed", exit_code=3, error="the package exited 3"))
    assert failed["error"] == {"code": "exit_status", "message": "the package exited 3"}
    assert wire.response(record(status="failed", error="no worker"))["error"]["code"] == "server_error"
    assert wire.response(record(status="incomplete"))["incomplete_details"] == {"reason": "timeout"}
    running = wire.response(record(status="claimed"))
    assert running["status"] == "in_progress" and running["output"][0]["status"] == "in_progress"


def test_stream_events():
    r = record()

    async def output():
        yield "stdout", "he"
        yield "stderr", "warn"
        yield "stdout", "llo"

    async def ended():
        return record(status="completed", output="shaped", stdout="hello", stderr="warn", exit_code=0)

    async def collect():
        return [e async for e in wire.stream(r, output(), ended)]
    events = asyncio.run(collect())
    parsed = [json.loads(e.split("data: ", 1)[1]) for e in events]
    kinds = [p["type"] for p in parsed]
    assert kinds[:4] == ["response.created", "response.in_progress", "response.output_item.added", "response.content_part.added"]
    assert [p["delta"] for p in parsed if p["type"] == "response.output_text.delta"] == ["he", "llo"]
    assert kinds[-1] == "response.completed" and parsed[-1]["response"]["output"][0]["content"][0]["text"] == "shaped"
    assert [p["sequence_number"] for p in parsed] == list(range(1, len(parsed) + 1))
    assert [p["text"] for p in parsed if p["type"] == "response.output_text.done"] == ["shaped"]
