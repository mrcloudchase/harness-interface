"""Pass dsh's NDJSON through untouched; write session id, summed usage and status to HI_OUTPUT.
`session` carries sessionId; each `status` step_end carries that step's usage; `status` turn_end
carries the reason; `final` is the answer."""
import json
import os
import sys

out, usage = {}, {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    t = ev.get("type")
    if t == "session" and ev.get("sessionId"):
        out["session_id"] = ev["sessionId"]
    elif t == "status" and ev.get("phase") == "step_end" and isinstance(ev.get("usage"), dict):
        u = ev["usage"]
        usage["input_tokens"] += int(u.get("inputTokens") or 0)
        usage["output_tokens"] += int(u.get("outputTokens") or 0)
        usage["cache_read_tokens"] += int(u.get("cacheReadTokens") or 0)
        usage["cache_write_tokens"] += int(u.get("cacheWriteTokens") or 0)
        out["usage"] = usage
    elif t == "status" and ev.get("phase") == "turn_end":
        out["status"] = "ok" if (ev.get("reason") or {}).get("kind") == "completed" else "fail"
    elif t == "error":
        out["status"] = "fail"
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
