"""Pass Gemini CLI's stream-json through; write session id, answer, usage and status. `init`
carries session_id; assistant `message` events carry text deltas; `result` carries stats."""
import json
import os
import sys

out, text = {}, []
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    t = ev.get("type")
    if t == "init" and ev.get("session_id"):
        out["session_id"] = ev["session_id"]
    elif t == "message" and ev.get("role") == "assistant":
        text.append(str(ev.get("content") or ""))
    elif t == "result":
        out["status"] = "ok" if ev.get("status") == "success" else "fail"
        out["usage"] = ev.get("stats")
    elif t == "error":
        out["status"] = "fail"
out["answer"] = "".join(text)
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
