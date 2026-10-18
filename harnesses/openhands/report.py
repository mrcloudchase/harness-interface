"""Pass OpenHands' output through untouched. The answer is the last agent MessageEvent's text;
`Conversation ID: <hex>` on exit is the resume handle (as a dashed UUID). Usage is not printed
in headless mode (it lives in the conversation's base_state.json), so none is reported. A turn that
errored, or ended with no agent message, failed: OpenHands still exits 0."""
import json
import os
import sys
import uuid

out = {}
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    s = line.strip()
    if s.startswith("Conversation ID:"):
        try:
            out["session_id"] = str(uuid.UUID(s.split(":", 1)[1].strip()))
        except ValueError:
            pass
        continue
    try:
        ev = json.loads(s)
    except ValueError:
        continue
    if ev.get("kind") == "MessageEvent" and ev.get("source") == "agent":
        content = (ev.get("llm_message") or {}).get("content") or []
        out["answer"] = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        out["status"] = "ok"
    if ev.get("kind") in ("AgentErrorEvent", "ConversationErrorEvent"):
        out["status"] = "fail"
out.setdefault("status", "fail")
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
