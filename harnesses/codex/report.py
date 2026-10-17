"""Pass Codex's --json events through untouched; write session id, usage, status and the answer
to HI_OUTPUT. thread.started carries thread_id; turn.completed carries usage; the last
agent_message is the answer; turn.failed / error mean failure."""
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
    t = ev.get("type", "")
    if t == "thread.started" and ev.get("thread_id"):
        out["session_id"] = ev["thread_id"]
    if t == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
        out["answer"] = str(ev["item"].get("text") or "")
    if t == "turn.completed":
        out["status"], out["usage"] = "ok", ev.get("usage")
    if t in ("turn.failed", "error"):
        out["status"] = "fail"
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
