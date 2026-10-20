"""Claude Code adapter: stream-json on stdin.

claude -p --input-format stream-json --output-format stream-json --verbose --replay-user-messages
- the task and every steer are one `user` line each; claude merges a steer into the running turn, or
  runs it as the next turn when it lands after the model's last tool call;
- done = a `result` with every user line sent echoed back (`isReplay`): nothing is queued
  (`result.queued_turn_count` is unreliable);
- stop = a `control_request` interrupt; the `result` that follows ends the response `stopped`;
- resume: the session id, chosen up front (`--session-id`) and written to HI_OUTPUT before claude starts;
- MCP servers: `$HOME/.claude/mcp.json`, when the folder's home/ ships one (`--mcp-config`);
- usage: each `result`'s, summed, in the five contract keys; cost: claude's `total_cost_usd`, which is
  cumulative over a session, less what earlier responses spent; null when claude doesn't know the
  model's price (`costBasis: unknown`, as for any model outside its own price list).
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import USAGE, Adapter  # noqa: E402

CLAUDE = os.path.join(os.environ.get("HOME", "."), ".claude")
SPENT = os.path.join(os.environ.get("HOME", "."), ".hi-cost")       # the session's total so far, by session id
FROM_RESULT = {"input_tokens": "input_tokens", "output_tokens": "output_tokens",
               "cache_read_input_tokens": "cache_read_tokens", "cache_creation_input_tokens": "cache_write_tokens"}


def usage_of(raw):
    """A `result`'s usage in the contract's keys."""
    out = {key: raw[name] for name, key in FROM_RESULT.items() if isinstance(raw.get(name), int)}
    thinking = (raw.get("output_tokens_details") or {}).get("thinking_tokens")
    if isinstance(thinking, int):
        out["reasoning_tokens"] = thinking
    return out


class ClaudeCodeAdapter(Adapter):
    stop_grace_s = 15.0

    def start(self, request):
        self.sid = request["resume"] or str(uuid.uuid4())
        self.out.write(resume=self.sid)
        argv = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--replay-user-messages", "--dangerously-skip-permissions"]
        if request["model"]:
            argv += ["--model", request["model"]]
        if os.path.isfile(os.path.join(CLAUDE, "mcp.json")):
            argv += ["--mcp-config", os.path.join(CLAUDE, "mcp.json")]
        argv += ["--resume", self.sid] if request["resume"] else ["--session-id", self.sid]
        self.cli = self.spawn(argv)
        self.sent = self.replayed = 0
        self.usage, self.known_cost, self.spent = dict.fromkeys(USAGE, 0), True, self.load_spent()
        self.user(request["task"])

    def write(self, obj):
        self.cli.stdin.write(json.dumps(obj) + "\n")
        self.cli.stdin.flush()

    def user(self, text):
        self.sent += 1
        self.write({"type": "user", "message": {"role": "user", "content": text}, "parent_tool_use_id": None,
                    "session_id": self.sid})

    def on_line(self, source, line):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return self.emit({"type": "hi.text", "text": line})
        self.emit(ev)                                # claude's own events, unchanged
        kind = ev.get("type")
        if kind == "user" and ev.get("isReplay"):
            self.replayed += 1
            if self.replayed > 1:                    # the first replay is the task itself
                self.accepted_steer()
        elif kind == "result":
            self.on_result(ev)

    def on_result(self, ev):
        for k, v in usage_of(ev.get("usage") or {}).items():
            self.usage[k] += v
        models = (ev.get("modelUsage") or {}).values()
        self.known_cost = self.known_cost and not any(m.get("costBasis") == "unknown" for m in models)
        fields = {"answer": ev.get("result") or self.out.data["answer"], "usage": self.usage}
        total = ev.get("total_cost_usd")
        if isinstance(total, (int, float)):
            fields["cost_usd"] = round(total - self.spent, 6) if self.known_cost else None
            self.save_spent(total)
        self.out.write(**fields)
        if self.stopping:
            self.finish("stopped")
        elif self.replayed >= self.sent:             # else a queued steer runs as the next turn
            self.finish("fail" if ev.get("is_error") else "ok")

    def steer(self, text):
        self.user(text)

    def stop(self):
        self.write({"type": "control_request", "request_id": "hi-stop-" + uuid.uuid4().hex[:8],
                    "request": {"subtype": "interrupt"}})

    def load_spent(self):
        try:
            with open(os.path.join(SPENT, self.sid)) as f:
                return float(f.read())
        except (OSError, ValueError):
            return 0.0

    def save_spent(self, total):
        os.makedirs(SPENT, exist_ok=True)
        with open(os.path.join(SPENT, self.sid), "w") as f:
            f.write(str(total))


if __name__ == "__main__":
    ClaudeCodeAdapter().main()
