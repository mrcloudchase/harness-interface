"""Pass Grok's streaming-json through untouched; write session id, usage, status and the answer to
HI_OUTPUT. `text` lines are deltas (the ones after the last tool_call form the answer); `end`
carries sessionId, usage and stopReason; `error` means failure."""
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
    if t == "text":
        text.append(str(ev.get("data") or ""))
    elif t == "tool_call":
        text = []
    elif t == "end":
        out["session_id"] = ev.get("sessionId")
        out["usage"] = ev.get("usage")
        out["cost_usd"] = ev.get("total_cost_usd")
        out["status"] = "ok" if ev.get("stopReason") in ("end_turn", None) else "fail"
    elif t == "error":
        out["status"] = "fail"
out["answer"] = "".join(text)
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
