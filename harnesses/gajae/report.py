"""Pass gjc's JSON events through untouched; write session id, summed usage, cost, status and the
answer to HI_OUTPUT. `session` carries the id; each `turn_end` carries an assistant message with
text, usage and cost; the last one with text is the answer."""
import json
import os
import sys

out, usage, cost = {}, {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, 0.0
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    t = ev.get("type")
    if t == "session" and ev.get("id"):
        out["session_id"] = ev["id"]
    elif t == "turn_end" and (ev.get("message") or {}).get("role") == "assistant":
        m = ev["message"]
        text = "".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
        if text:
            out["answer"] = text
        u = m.get("usage") or {}
        for k in usage:
            usage[k] += int(u.get(k) or 0)
        cost += float((u.get("cost") or {}).get("total") or 0)
        out["usage"], out["cost_usd"] = usage, cost
        out["status"] = "fail" if m.get("stopReason") == "error" else "ok"
    elif t == "error":
        out["status"] = "fail"
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
