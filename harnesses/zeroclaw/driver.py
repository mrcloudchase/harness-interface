"""One ZeroClaw turn over ACP: initialize, resume the session in HI_SESSION_ID or open a new one,
send the task, and print each session update as one JSON line. A final `result` line carries the
session id and the answer."""
import json
import os
import subprocess
import sys

proc = subprocess.Popen(["zeroclaw", "acp", "--config-dir", sys.argv[1]], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, text=True, cwd=os.environ["HI_WORKSPACE"], bufsize=1)
next_id, text = 0, []


def emit(ev):
    print(json.dumps(ev), flush=True)


def call(method, params):
    global next_id
    next_id += 1
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": next_id, "method": method, "params": params}) + "\n")
    proc.stdin.flush()
    for line in proc.stdout:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("id") == next_id and "method" not in msg:
            return msg
        if msg.get("method") == "session/request_permission":      # nobody to ask: tools are pre-approved in config
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": {"outcome": "cancelled"}}}) + "\n")
            proc.stdin.flush()
        elif msg.get("method") == "session/update":
            u = (msg.get("params") or {}).get("update") or {}
            emit(u)
            if u.get("sessionUpdate") == "agent_message_chunk":
                c = u.get("content") or {}
                text.append(c.get("text", "") if isinstance(c, dict) else "")
    return {}


try:
    call("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
    sid = os.environ.get("HI_SESSION_ID", "")
    if not (sid and "result" in call("session/resume", {"sessionId": sid})):
        sid = (call("session/new", {"cwd": os.environ["HI_WORKSPACE"], "agentAlias": "zeroclaw"}).get("result") or {}).get("sessionId", "")
    r = call("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": os.environ["HI_TASK"]}]})
    res = r.get("result") or {}
    ok = bool(res) and res.get("stopReason") in (None, "", "end_turn")
    emit({"type": "result", "session_id": sid, "ok": ok, "answer": str(res.get("content") or "".join(text)),
          "error": (r.get("error") or {}).get("message")})
finally:
    proc.stdin.close()
    proc.wait(timeout=30)
