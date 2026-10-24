#!/usr/bin/env python3
"""The filter: foobar's native events in on stdin, Responses output items out on stdout, one JSON
object per line, as they happen. Two kinds of line:

    {"item": {…}}      a finished item: reasoning, function_call, function_call_output, mcp_call
    {"delta": "…"}     a piece of the assistant's message text

The template turns these into the response's output list and the stream's events; it never reads
foobar's events itself. A package for another CLI replaces this file and run.sh, nothing else.
"""
import json
import sys


def out(item):
    print(json.dumps({"item": item}), flush=True)


n = 0
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        continue                                     # a stray print from the CLI: not an event
    n += 1
    kind = ev.get("ev")
    if kind == "think":
        out({"type": "reasoning", "id": f"rs_{n}", "summary": [{"type": "summary_text", "text": ev["text"]}], "status": "completed"})
    elif kind == "tool":
        out({"type": "function_call", "id": f"fc_{ev['id']}", "call_id": f"call_{ev['id']}", "name": ev["name"],
             "arguments": json.dumps(ev["args"]), "status": "completed"})
    elif kind == "tool_result":
        out({"type": "function_call_output", "id": f"fco_{ev['id']}", "call_id": f"call_{ev['id']}", "output": ev["out"],
             "status": "completed" if ev["ok"] else "failed"})
    elif kind == "mcp":
        out({"type": "mcp_call", "id": f"mcp_{ev['id']}", "server_label": ev["server"], "name": ev["tool"],
             "arguments": json.dumps(ev["args"]), "output": ev["out"], "error": None, "status": "completed"})
    elif kind == "say":
        print(json.dumps({"delta": ev["delta"]}), flush=True)
