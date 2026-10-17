"""Pass Cline's JSON events through untouched; write usage, cost, status and the answer to
HI_OUTPUT. The last text `content_end` agent_event is the answer (else `done.text`); `run_result`
carries usage (its own key names, totalCost in USD) and finishReason; `error` means failure.
No session id: Cline cannot resume headlessly."""
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
    t, e = ev.get("type"), ev.get("event") or {}
    if t == "agent_event" and e.get("type") == "content_end" and e.get("contentType") == "text":
        out["answer"] = str(e.get("text") or "")
    elif t == "agent_event" and e.get("type") == "done":
        out.setdefault("answer", str(e.get("text") or ""))
    elif t == "run_result":
        out["usage"] = ev.get("usage")
        out["cost_usd"] = (ev.get("usage") or {}).get("totalCost")
        out["status"] = "ok" if ev.get("finishReason") == "completed" else "fail"
    elif t == "error":
        out["status"] = "fail"
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
