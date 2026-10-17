"""Pass Kimi Code's stream-json through untouched; write session id and the answer to HI_OUTPUT.
The last assistant line with `content` is the answer; the meta `session.resume_hint` line carries
the session id. It reports no usage in this mode."""
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
    if ev.get("role") == "assistant" and ev.get("content"):
        out["answer"] = str(ev["content"])
        out["status"] = "ok"
    if ev.get("type") == "session.resume_hint" and ev.get("session_id"):
        out["session_id"] = ev["session_id"]
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
