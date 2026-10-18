"""Pass Goose's output through untouched; write session id, usage, cost, status and the answer to
HI_OUTPUT. The banner line `<id> · <dir>` carries the session id; assistant `message` events
stream text per message id (the last message's text is the answer); `complete` carries usage and
cost; `error` means failure."""
import json
import os
import re
import sys

out, texts = {}, {}
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    m = re.search(r"(\d{8}_\d+) · ", line)
    if m and "session_id" not in out:
        out["session_id"] = m.group(1)
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    t = ev.get("type")
    if t == "message" and (ev.get("message") or {}).get("role") == "assistant":
        msg = ev["message"]
        texts.setdefault(msg.get("id"), []).extend(c.get("text", "") for c in msg.get("content", []) if c.get("type") == "text")
        if any(c.get("type") == "error" for c in msg.get("content", [])):
            out["status"] = "fail"
    elif t == "complete":
        out["usage"] = {k: v for k, v in ev.items() if k.endswith("tokens")}
        out["cost_usd"] = ev.get("cost_usd")
        out.setdefault("status", "ok")
    elif t == "error":
        out["status"] = "fail"
if texts:
    out["answer"] = "".join(list(texts.values())[-1]).strip()
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
