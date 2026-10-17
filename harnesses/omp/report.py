"""Pass omp's JSON events through untouched; write session id, usage, cost and the answer to
HI_OUTPUT. `session` carries the id; the last assistant `message_end` carries the text, usage
and cost (the same shape as pi)."""
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
    if ev.get("type") == "session" and ev.get("id"):
        out["session_id"] = ev["id"]
    if ev.get("type") == "message_end" and (ev.get("message") or {}).get("role") == "assistant":
        m = ev["message"]
        out["answer"] = "".join(c.get("text", "") for c in m.get("content", []) if c.get("type") == "text")
        usage = m.get("usage") or {}
        out["usage"] = {k: v for k, v in usage.items() if isinstance(v, (int, float))}
        out["cost_usd"] = (usage.get("cost") or {}).get("total")
        out["status"] = "ok" if m.get("stopReason") in ("stop", "toolUse", None) else "fail"
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
