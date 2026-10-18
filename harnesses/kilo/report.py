"""Pass Kilo's JSON events (OpenCode's format) through untouched; write session id, summed usage, cost, status and
the answer to HI_OUTPUT. Every event carries sessionID; `text` parts carry the words (the last
message's are the answer); each `step_finish` carries that step's tokens and cost; `error` fails."""
import json
import os
import sys

out, texts, usage = {}, {}, {"input": 0, "output": 0, "reasoning": 0, "cache_write": 0, "cache_read": 0}
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("sessionID"):
        out["session_id"] = ev["sessionID"]
    p = ev.get("part") or {}
    if ev.get("type") == "text":
        texts.setdefault(p.get("messageID"), []).append(p.get("text") or "")
    elif ev.get("type") == "step_finish":
        t = p.get("tokens") or {}
        usage["input"] += int(t.get("input") or 0); usage["output"] += int(t.get("output") or 0)
        usage["reasoning"] += int(t.get("reasoning") or 0)
        usage["cache_write"] += int((t.get("cache") or {}).get("write") or 0)
        usage["cache_read"] += int((t.get("cache") or {}).get("read") or 0)
        out["usage"] = usage
        out["cost_usd"] = out.get("cost_usd", 0) + float(p.get("cost") or 0)
        out["status"] = "fail" if p.get("reason") == "error" else "ok"
    elif ev.get("type") == "error":
        out["status"] = "fail"
if texts:
    out["answer"] = "".join(list(texts.values())[-1])
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
