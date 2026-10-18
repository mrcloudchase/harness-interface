"""Pass the ACP conversation through untouched; write the session, the status and the answer to
HI_OUTPUT. The session id is the one every `session/update` carries. The answer is the text the
agent streamed after the prompt was sent, from its last tool call on; the history a loaded
session replays comes before the prompt, so it is not counted. The prompt's result says how the
turn ended. ACP carries no usage."""
import json
import os
import sys

out, prompt_id, text = {"status": "fail"}, None, []
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    params = msg.get("params") or {}
    if msg.get("method") == "session/prompt":
        prompt_id, text = msg.get("id"), []
    elif msg.get("method") == "session/update":
        out["session_id"] = params.get("sessionId")
        update = params.get("update") or {}
        if prompt_id is not None and update.get("sessionUpdate") == "agent_message_chunk":
            text.append((update.get("content") or {}).get("text") or "")
        elif update.get("sessionUpdate") == "tool_call":
            text = []
    elif prompt_id is not None and msg.get("id") == prompt_id and "method" not in msg:
        out["status"] = "ok" if (msg.get("result") or {}).get("stopReason") == "end_turn" else "fail"
out["answer"] = "".join(text).strip()
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
