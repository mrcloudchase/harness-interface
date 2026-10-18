"""Pass mimo's JSON events through untouched; write session id, summed usage, cost, status and the
answer to HI_OUTPUT. Every event carries sessionID; `text` parts of the last step are the answer;
each `step_finish` carries that step's tokens and cost; `error` means failure."""
import json
import os
import sys

out, usage, cost, texts = {}, {"input": 0, "output": 0, "reasoning": 0, "cache_read": 0, "cache_write": 0}, 0.0, []
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    t, part = ev.get("type"), ev.get("part") or {}
    if ev.get("sessionID"):
        out["session_id"] = ev["sessionID"]
    if t == "step_start":
        texts = []
    elif t == "text":
        texts.append(part.get("text") or "")
    elif t == "step_finish":
        tok = part.get("tokens") or {}
        usage["input"] += int(tok.get("input") or 0)
        usage["output"] += int(tok.get("output") or 0)
        usage["reasoning"] += int(tok.get("reasoning") or 0)
        usage["cache_read"] += int((tok.get("cache") or {}).get("read") or 0)
        usage["cache_write"] += int((tok.get("cache") or {}).get("write") or 0)
        cost += float(part.get("cost") or 0)
        out["usage"], out["cost_usd"], out["status"] = usage, cost, "ok"
    elif t == "error":
        out["status"] = "fail"
    if texts:
        out["answer"] = "".join(texts)
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
