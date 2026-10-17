"""Pass mcode's stream-json through untouched; write session id, usage, status and the answer to
HI_OUTPUT. Every event carries sessionId; turn.completed carries usage; exec.completed carries
the final status and output."""
import json
import os
import sys

out = {}
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("sessionId"):
        out["session_id"] = ev["sessionId"]
    t = ev.get("type")
    if t == "turn.completed":
        out["usage"] = ev.get("usage")
    elif t == "exec.completed":
        r = ev.get("result") or {}
        out["status"] = "ok" if r.get("status") == "succeeded" else "fail"
        out["answer"] = str(r.get("output") or "")
    elif t == "turn.failed":
        out["status"] = "fail"
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
