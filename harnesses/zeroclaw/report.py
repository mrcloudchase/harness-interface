"""Pass the driver's lines through; the final `result` line is the session id and the answer."""
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
    if ev.get("type") == "result":
        out = {"session_id": ev.get("session_id"), "answer": ev.get("answer", ""), "status": "ok" if ev.get("ok") else "fail"}
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
