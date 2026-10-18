"""Drive `cline --acp`, the Agent Client Protocol: JSON-RPC 2.0, one message per line on stdio.
Start a session, or load the one HI_SESSION_ID names, send the task as one prompt, and answer
every permission request with allow. Every message, both ways, is printed as it goes, so stdout
is the whole conversation."""
import json
import os
import subprocess
import sys

agent = subprocess.Popen(["cline", "--acp", "--auto-approve", "true"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, text=True, bufsize=1)
ids = iter(range(1, 1_000_000))


def send(msg: dict) -> None:
    line = json.dumps({"jsonrpc": "2.0", **msg})
    print(line, flush=True)
    agent.stdin.write(line + "\n")
    agent.stdin.flush()


def call(method: str, params: dict) -> dict:
    """Send a request and return its result, passing on what arrives in between."""
    rid = next(ids)
    send({"id": rid, "method": method, "params": params})
    for line in agent.stdout:
        print(line, end="", flush=True)
        msg = json.loads(line)
        if msg.get("id") == rid and "method" not in msg:
            if "error" in msg:
                sys.exit(f"{method}: {msg['error']}")
            return msg["result"]
        if msg.get("method") == "session/request_permission":
            allow = next(o for o in msg["params"]["options"] if o["kind"].startswith("allow"))
            send({"id": msg["id"], "result": {"outcome": {"outcome": "selected", "optionId": allow["optionId"]}}})
    sys.exit(f"{method}: cline exited")


call("initialize", {"protocolVersion": 1, "clientCapabilities": {}})
where = {"cwd": os.getcwd(), "mcpServers": []}
session = os.environ.get("HI_SESSION_ID")
if session:
    call("session/load", {"sessionId": session, **where})    # replays the history before the prompt
else:
    session = call("session/new", where)["sessionId"]
call("session/prompt", {"sessionId": session, "prompt": [{"type": "text", "text": os.environ["HI_TASK"]}]})
agent.stdin.close()
agent.wait()
