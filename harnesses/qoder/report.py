"""Pass Qoder's stream-json through untouched; write what the server reads to HI_OUTPUT.
Same shape as Claude Code: session_id on the system/init line; usage, status, cost and the
answer on the result line."""
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
    if ev.get("type") == "system" and ev.get("session_id"):
        out["session_id"] = ev["session_id"]
    if ev.get("type") == "result":
        out["status"] = "fail" if ev.get("is_error") else "ok"
        out["usage"] = ev.get("usage")
        out["cost_usd"] = ev.get("total_cost_usd")
        out["answer"] = ev.get("result") or ""
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
