"""Pass OpenSquilla's JSON result through untouched; write session id, usage, cost, status and the
answer to HI_OUTPUT. The object carries status, session_key, text and usage (with cost_usd)."""
import json
import os
import sys

body = sys.stdin.read()
sys.stdout.write(body)
sys.stdout.flush()
out = {}
try:
    r = json.loads(body)
except ValueError:
    r = {}
if r:
    out["status"] = "ok" if r.get("status") == "ok" and not r.get("errors") else "fail"
    out["session_id"] = r.get("session_key")
    out["answer"] = str(r.get("text") or "")
    out["usage"] = {k: v for k, v in (r.get("usage") or {}).items() if isinstance(v, (int, float))}
    out["cost_usd"] = (r.get("usage") or {}).get("cost_usd")
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
