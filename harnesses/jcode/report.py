"""Pass J-Code's one JSON result through untouched; write its session id, answer and usage."""
import json
import os
import sys

raw = sys.stdin.read()
sys.stdout.write(raw)
try:
    r = json.loads(raw)
    out = {"session_id": r.get("session_id"), "answer": r.get("text") or "", "usage": r.get("usage"), "status": "ok"}
except ValueError:
    out = {"status": "fail"}
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
