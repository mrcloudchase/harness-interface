"""Hermes Agent adapter: ACP, JSON-RPC 2.0 over `hermes acp`'s stdio.

initialize -> session/new, or session/load to resume -> session/prompt, the main prompt, whose result
ends the response:
- a steer is another session/prompt, "/steer TEXT": hermes answers it at once and adds the text to the
  last tool result before its next model call. A steer answered after the model's last call is never
  seen by it, so it runs as the next prompt;
- stop = session/cancel: hermes 0.19.0 answers the main prompt with error -32603 or with stopReason
  "cancelled", and both mean stopped. `hermes acp` ignores SIGINT, so it only ever gets the cancel;
- what hermes loaded: before the main prompt, "/tools", which hermes answers itself, lists its tools in
  stdout, each MCP server's included; harness.json reports the skills it indexed and the hooks it took;
- resume: the ACP session id, written to HI_OUTPUT as soon as session/new returns it. session/load
  restores the base URL the session was made with, which is safe because the provider's URL (the
  gateway's, under the gateway) stays the same for the whole session;
- the key: hermes starts on a launcher that reads $HI_PROVIDER_KEY_FILE into its own os.environ, so
  the value is in no process's initial environment. hermes keeps it from the shells and MCP servers it
  starts, but not from shell hooks: start a hook with `env -u ANTHROPIC_API_KEY`;
- usage and cost: diffs of hermes's cumulative per-session counters in $HERMES_HOME/state.db, already
  named as the contract names them; cost is null when hermes has no price for the model.
"""
import json
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import USAGE, Adapter, JsonRpc  # noqa: E402

LAUNCH = ("import os, sys\n"
          "with open(os.environ['HI_PROVIDER_KEY_FILE']) as f:\n"
          "    os.environ['ANTHROPIC_API_KEY'] = f.read().strip()\n"
          "from hermes_cli.main import main\n"
          "sys.argv[0] = 'hermes'\n"
          "sys.exit(main())\n")
STEER_NOTES = ("⏩ Steer queued", "No active turn", "Queued for the next turn")   # hermes's own acks
COUNTERS = (*USAGE, "estimated_cost_usd", "cost_status")


def hermes_argv(*args: str) -> list:
    """`hermes ARGS`, on the launcher when there is a key file (the venv's own python, beside hermes)."""
    if not os.environ.get("HI_PROVIDER_KEY_FILE"):
        return ["hermes", *args]
    venv_bin = os.path.dirname(os.path.realpath(shutil.which("hermes")))
    return [os.path.join(venv_bin, "python"), "-c", LAUNCH, *args]


class HermesAdapter(Adapter):
    stop_grace_s = 15.0

    def start(self, request):
        self.db = os.path.join(os.environ["HERMES_HOME"], "state.db")
        self.sid, self.task = request["resume"], request["task"]
        self.before = self.counters()
        self.cli = self.spawn(hermes_argv("acp", "--accept-hooks"))
        self.rpc = JsonRpc(self.cli, self.answer)
        self.main_id = self.main_result = None     # the prompt that ends the response, and its reply
        self.loading, self.replayed = False, 0
        self.text: list[str] = []                  # agent text since the last tool call: the answer
        self.waiting: list[str] = []               # steers that came before the main prompt
        self.unacked = 0                           # steers hermes has not answered yet
        self.undelivered: list[str] = []           # answered steers no model call has seen yet
        self.rpc.call("initialize", {"protocolVersion": 1, "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}, self.on_init)

    def answer(self, method, params):
        """hermes asks the client: allow every permission it asks for, once."""
        if method != "session/request_permission":
            return {}
        options = (params or {}).get("options", [])
        pick = next((o["optionId"] for o in options if o.get("kind") == "allow_once"), "allow_once")
        return {"outcome": {"outcome": "selected", "optionId": pick}}

    def prompt(self, text, then):
        return self.rpc.call("session/prompt", {"sessionId": self.sid, "prompt": [{"type": "text", "text": text}]},
                             then)

    def on_line(self, source, line):
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            return self.emit({"type": "hi.text", "text": line})
        if self.loading and m.get("method") == "session/update":     # session/load replays history: not news
            self.replayed += 1
            return
        self.emit(m)                                                  # hermes's own messages, unchanged
        if self.rpc.dispatch(m) and m.get("method") == "session/update":
            self.on_update(m["params"].get("update", {}))

    def on_update(self, u):
        kind = u.get("sessionUpdate")
        if kind == "agent_message_chunk":
            text = u.get("content", {}).get("text", "")
            if not text.startswith(STEER_NOTES):
                self.text.append(text)
        elif kind in ("tool_call", "tool_call_update"):
            self.text = []
            if kind == "tool_call":                # a tool ran, so another model call follows,
                self.undelivered = []              # and it carries every steer answered so far

    # --- the session ---------------------------------------------------------------------------
    def on_init(self, result, error):
        if error:
            return self.finish("fail", answer=f"hermes acp initialize: {error}")
        params = {"cwd": os.getcwd(), "mcpServers": []}
        if self.sid:
            self.loading = True
            self.rpc.call("session/load", {"sessionId": self.sid, **params}, self.on_session)
        else:
            self.rpc.call("session/new", params, self.on_session)

    def on_session(self, result, error):
        self.loading = False
        if result is None or (not self.sid and "sessionId" not in result):     # load answers null if unknown
            return self.finish("fail", answer=f"no hermes session {self.sid or ''}: {error}")
        if self.sid:
            self.emit({"type": "hi.replayed", "updates": self.replayed})
        else:
            self.sid = result["sessionId"]
            self.out.write(resume=self.sid)       # early: as soon as the id is known
        self.prompt("/tools", lambda result, error: self.begin())   # answered by hermes itself, no model call

    def begin(self):
        """The main prompt, once hermes has listed its tools (the MCP servers' among them) in stdout."""
        if self.stopping:
            return self.finish("stopped")
        self.text = []
        self.main_id = self.prompt(self.task, self.on_main_done)
        for text in self.waiting:
            self.steer(text)
        self.waiting = []

    def steer(self, text):
        if self.main_id is None:
            self.waiting.append(text)
        elif self.main_result is None:            # busy: steer the running turn
            self.unacked += 1
            self.prompt("/steer " + text, lambda result, error: self.on_steer_ack(text, error))
        else:                                     # the main turn has just ended: run it as the next one
            self.undelivered.append(text)
            self.accepted_steer()
            self.settle()

    def on_steer_ack(self, text, error):
        self.unacked -= 1
        if not error:
            self.accepted_steer()
        self.undelivered.append(text)             # until a tool call shows a model call carried it
        self.settle()

    def on_main_done(self, result, error):
        self.main_result = {"result": result, "error": error}
        self.settle()

    def settle(self):
        """Finish when the main prompt has ended and no steer is in flight or unseen."""
        m = self.main_result
        if m is None or self.finished:
            return
        result = m["result"] or {}
        if self.stopping or result.get("stopReason") == "cancelled":
            return self.finish("stopped", **self.report())
        if m["error"]:
            return self.finish("fail", **self.report(answer=f"hermes: {m['error'].get('message')}"))
        if self.unacked:
            return
        if self.undelivered:                      # it landed after the model's last call
            text, self.undelivered, self.text, self.main_result = "\n".join(self.undelivered), [], [], None
            self.main_id = self.prompt(text, self.on_main_done)
            return
        report = self.report()
        failed = not result.get("usage") or report["answer"].startswith("API call failed")
        self.finish("fail" if failed else "ok", **report)

    def stop(self):
        if self.main_id is None or self.main_result is not None:
            return self.finish("stopped", **self.report())
        self.rpc.notify("session/cancel", {"sessionId": self.sid})

    # --- hermes's state.db ---------------------------------------------------------------------
    def report(self, answer=None):
        after = self.counters()
        usage = {k: after[k] - self.before.get(k, 0) for k in USAGE if k in after}
        cost = after.get("estimated_cost_usd")
        if cost is not None and after.get("cost_status") not in (None, "unknown"):
            cost = round(cost - (self.before.get("estimated_cost_usd") or 0), 6)
        else:
            cost = None
        return {"answer": "".join(self.text).strip() if answer is None else answer, "usage": usage, "cost_usd": cost}

    def counters(self):
        if not (self.sid and os.path.exists(self.db)):
            return {}
        try:
            with sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=5) as db:
                row = db.execute(f"SELECT {','.join(COUNTERS)} FROM sessions WHERE id=?", (self.sid,)).fetchone()
        except sqlite3.Error:
            return {}
        return {k: v for k, v in zip(COUNTERS, row or ()) if v is not None}


if __name__ == "__main__":
    HermesAdapter().main()
