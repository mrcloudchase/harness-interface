"""Claude Code adapter (pattern P1: stream-json on stdin).

claude -p --input-format stream-json --output-format stream-json --verbose --replay-user-messages
- task and every steer = one `user` line; claude merges a steer into the running turn, or runs it
  as the next turn when it lands after the model's last tool call;
- done = a `result` with every user line we sent echoed back (`isReplay`), i.e. nothing queued
  (`result.queued_turn_count` is unreliable);
- stop = `control_request` interrupt; the `result` that follows ends the run as `stopped`;
- resume id: chosen up front (`--session-id`), written to HI_OUTPUT before claude starts.
"""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import Adapter  # noqa: E402

COST_DIR = os.path.join(os.environ.get("HOME", "."), ".hi-cost")   # total_cost_usd is per session, cumulative


class ClaudeCodeAdapter(Adapter):
    stop_grace_s = 15.0

    def start(self, request):
        self.sid = request["resume"] or str(uuid.uuid4())
        self.out.write(resume=self.sid)
        argv = ["claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                "--replay-user-messages", "--dangerously-skip-permissions"]
        if request["model"]:
            argv += ["--model", request["model"]]
        argv += ["--resume", self.sid] if request["resume"] else ["--session-id", self.sid]
        self.cli = self.spawn(argv)
        self.sent = self.replayed = 0
        self.usage, self.cost0 = {}, self.load_cost()
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
        self.emit(ev)
        kind = ev.get("type")
        if kind == "user" and ev.get("isReplay"):
            self.replayed += 1
            if self.replayed > 1:                       # the first replay is the task itself
                self.accepted_steer()
        elif kind == "result":
            self.on_result(ev)

    def on_result(self, ev):
        for k, v in (ev.get("usage") or {}).items():
            if isinstance(v, (int, float)):
                self.usage[k] = self.usage.get(k, 0) + v
        fields = {"answer": ev.get("result") or self.out.data["answer"], "usage": self.usage}
        total = ev.get("total_cost_usd")
        if isinstance(total, (int, float)):
            fields["cost_usd"] = round(total - self.cost0, 6)
            self.save_cost(total)
        self.out.write(**fields)
        if self.stopping_since:
            self.finish("stopped")
        elif self.replayed >= self.sent:                # else a queued steer runs as the next turn
            self.finish("fail" if ev.get("is_error") else "ok")

    def steer(self, text):
        self.user(text)

    def stop(self):
        self.write({"type": "control_request", "request_id": "hi-stop-" + uuid.uuid4().hex[:8],
                    "request": {"subtype": "interrupt"}})

    def load_cost(self):
        try:
            with open(os.path.join(COST_DIR, self.sid)) as f:
                return float(f.read())
        except (OSError, ValueError):
            return 0.0

    def save_cost(self, total):
        os.makedirs(COST_DIR, exist_ok=True)
        with open(os.path.join(COST_DIR, self.sid), "w") as f:
            f.write(str(total))


if __name__ == "__main__":
    ClaudeCodeAdapter().main()
