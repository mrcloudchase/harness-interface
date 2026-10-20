"""The template's adapter: drives the stand-in CLI over its RPC mode. A real harness replaces the
four methods below and keeps the shape: start → write resume early → pass events through →
steer while busy, prompt while idle → finish from the CLI's events, never its exit code."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import Adapter  # noqa: E402


class StandinAdapter(Adapter):
    stop_grace_s = 10.0

    def start(self, request):
        argv = ["standin", "--model", request["model"] or "standin-1"]
        if request["resume"]:
            argv += ["--resume", request["resume"]]
        self.cli = self.spawn(argv)
        self.queued, self.usage = 0, {"input_tokens": 0, "output_tokens": 0}
        task = request["task"] if not request["instructions"] else f"{request['instructions']}\n\n{request['task']}"
        self.send({"type": "prompt", "text": task})

    def send(self, cmd):
        self.cli.stdin.write(json.dumps(cmd) + "\n")
        self.cli.stdin.flush()

    def on_line(self, source, line):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return self.emit({"type": "hi.text", "text": line})
        self.emit(ev)
        kind = ev.get("type")
        if kind == "session":
            self.out.write(resume=ev["id"])          # early: as soon as the id is known
        elif kind == "steer_accepted":
            self.queued -= 1
            self.accepted_steer()
        elif kind == "turn_end":
            for k, v in ev.get("usage", {}).items():
                self.usage[k] = self.usage.get(k, 0) + v
            self.out.write(answer=ev["text"], usage=self.usage, cost_usd=0.0)
            if ev["reason"] == "aborted":
                self.finish("stopped")
            elif self.queued == 0:                   # else a steer that raced the end runs as the next turn
                self.finish("ok")

    def steer(self, text):                           # the CLI queues it, or runs it next if idle
        self.queued += 1
        self.send({"type": "steer", "text": text})

    def stop(self):
        self.send({"type": "abort"})


if __name__ == "__main__":
    StandinAdapter().main()
