"""Hermes Agent over ACP: `hermes acp` speaks JSON-RPC 2.0 on stdio (survey pattern P3).

initialize -> session/new | session/load -> session/prompt (the main prompt; its result ends the
response). Steer = another session/prompt "/steer TEXT": hermes answers it at once (end_turn) and
appends the text to the last tool result before its next model call. A steer acked after the
model's last call is never seen by it, so it is run as the next prompt. Stop = session/cancel:
hermes 0.19.0 answers the main prompt with error -32603 instead of stopReason "cancelled"; both
mean stopped. `hermes acp` ignores SIGINT, so it only ever gets session/cancel from us.
Usage and cost: diffs of hermes's cumulative per-session counters in $HERMES_HOME/state.db."""
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import Adapter, child_env, provider_key  # noqa: E402

STEER_NOTES = ("⏩ Steer queued", "No active turn", "Queued for the next turn")   # hermes's own acks
COUNTERS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens",
            "api_call_count", "estimated_cost_usd", "cost_status")


class HermesAdapter(Adapter):
    stop_grace_s = 15.0

    def start(self, request):
        self.db = os.path.join(os.environ["HERMES_HOME"], "state.db")
        self.sid, self.model = request["resume"], request["model"]
        if self.sid:
            self.repoint()
        self.before = self.counters()
        env = {"HI_MODEL": self.model}
        if os.environ.get("HI_PROVIDER_KEY_FILE"):
            env["ANTHROPIC_API_KEY"] = provider_key()          # hermes's environ only, never the adapter's
        self.cli = self.spawn(["hermes", "acp", "--accept-hooks"], env=child_env(**env))
        self.task, self.next_id, self.calls = request["task"], 0, {}
        self.main = self.main_result = None        # id and result of the prompt that ends the response
        self.loading, self.replayed, self.cancelled = False, 0, False
        self.text: list[str] = []                  # agent text since the last tool call = the answer
        self.waiting: list[str] = []               # steers that came before the main prompt
        self.unacked: set[int] = set()             # steer calls hermes has not answered yet
        self.undelivered: list[str] = []           # acked steers no model call has seen yet
        self.call("initialize", {"protocolVersion": 1, "clientCapabilities": {
            "fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False}}, self.on_init)

    # --- JSON-RPC ------------------------------------------------------------------------------
    def send(self, msg):
        self.cli.stdin.write(json.dumps({"jsonrpc": "2.0", **msg}) + "\n")
        self.cli.stdin.flush()

    def call(self, method, params, then):
        self.next_id += 1
        self.calls[self.next_id] = then
        self.send({"id": self.next_id, "method": method, "params": params})
        return self.next_id

    def prompt(self, text, then):
        return self.call("session/prompt", {"sessionId": self.sid, "prompt": [{"type": "text", "text": text}]}, then)

    def on_line(self, source, line):
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            return self.emit({"type": "hi.text", "text": line})
        if "method" in m and "id" in m:                    # hermes asks us something
            return self.answer(m)
        if "method" in m:
            return self.on_update(m)
        self.emit(m)
        then = self.calls.pop(m.get("id"), None)
        if then:
            then(m)

    def answer(self, m):
        self.emit(m)
        if m["method"] == "session/request_permission":   # auto-allow, once
            opts = m.get("params", {}).get("options", [])
            pick = next((o["optionId"] for o in opts if o.get("kind") == "allow_once"), "allow_once")
            self.send({"id": m["id"], "result": {"outcome": {"outcome": "selected", "optionId": pick}}})
        else:
            self.send({"id": m["id"], "error": {"code": -32601, "message": "not supported by this client"}})

    def on_update(self, m):
        if self.loading:                                   # session/load replays history: not news
            self.replayed += 1
            return
        self.emit(m)
        u = m.get("params", {}).get("update", {})
        kind = u.get("sessionUpdate")
        if kind == "agent_message_chunk":
            text = u.get("content", {}).get("text", "")
            if not text.startswith(STEER_NOTES):
                self.text.append(text)
        elif kind in ("tool_call", "tool_call_update"):
            self.text = []
            if kind == "tool_call":                        # a tool ran, so another model call follows:
                self.undelivered = []                      # it will carry every steer acked so far

    # --- the session ---------------------------------------------------------------------------
    def on_init(self, m):
        if "error" in m:
            return self.finish("fail", answer=f"hermes acp initialize: {m['error']}")
        if self.sid:
            self.loading = True
            self.call("session/load", {"sessionId": self.sid, "cwd": os.getcwd(), "mcpServers": []}, self.on_session)
        else:
            self.call("session/new", {"cwd": os.getcwd(), "mcpServers": []}, self.on_session)

    def on_session(self, m):
        self.loading = False
        res = m.get("result")
        if res is None or (not self.sid and "sessionId" not in res):        # load answers null if unknown
            return self.finish("fail", answer=f"no hermes session {self.sid or ''}: {m.get('error')}".strip())
        if not self.sid:
            self.sid = m["result"]["sessionId"]
            self.out.write(resume=self.sid)                # early: as soon as the id is known
        else:
            self.emit({"type": "hi.replayed", "updates": self.replayed})
        if self.stopping_since:
            return self.finish("stopped")
        self.main = self.prompt(self.task, self.on_main_done)
        for text in self.waiting:
            self.steer(text)
        self.waiting = []

    def steer(self, text):
        if self.main is None:
            self.waiting.append(text)
        elif self.main_result is None:                     # busy: steer the running turn
            self.unacked.add(self.prompt("/steer " + text, lambda m, t=text: self.on_steer_ack(m, t)))
        else:                                              # main turn just ended: run it as the next one
            self.undelivered.append(text)
            self.accepted_steer()
            self.settle()

    def on_steer_ack(self, m, text):
        self.unacked.discard(m.get("id"))
        if "error" not in m:
            self.accepted_steer()
        self.undelivered.append(text)                      # until a tool call shows the model got it
        self.settle()

    def on_main_done(self, m):
        self.main_result = m
        self.settle()

    def settle(self):
        """Finish when the main prompt has ended and no steer is still in flight or unseen."""
        m = self.main_result
        if m is None or self.finished:
            return
        stop_reason = (m.get("result") or {}).get("stopReason")
        if self.cancelled or stop_reason == "cancelled":
            return self.finish("stopped", **self.report())
        if "error" in m:
            return self.finish("fail", **self.report(answer=f"hermes: {m['error'].get('message')}"))
        if self.unacked:
            return
        if self.undelivered:                               # landed after the model's last call
            text, self.undelivered, self.text, self.main_result = "\n".join(self.undelivered), [], [], None
            self.main = self.prompt(text, self.on_main_done)
            return
        report = self.report()
        failed = not (m.get("result") or {}).get("usage") or report["answer"].startswith("API call failed")
        self.finish("fail" if failed else "ok", **report)

    def stop(self):
        if self.main is None or self.main_result is not None:
            return self.finish("stopped", **self.report())
        self.cancelled = True
        self.send({"method": "session/cancel", "params": {"sessionId": self.sid}})

    # --- hermes's state.db ---------------------------------------------------------------------
    def report(self, answer=None):
        after = self.counters()
        usage = {k: after[k] - self.before.get(k, 0) for k in COUNTERS[:-2] if k in after}
        cost = after.get("estimated_cost_usd")                 # None when hermes has no price for the model
        known = cost is not None and after.get("cost_status") not in (None, "unknown")
        cost = round(cost - (self.before.get("estimated_cost_usd") or 0), 6) if known else None
        return {"answer": answer if answer is not None else "".join(self.text).strip(), "usage": usage, "cost_usd": cost}

    def counters(self):
        if not (self.sid and os.path.exists(self.db)):
            return {}
        try:
            with sqlite3.connect(f"file:{self.db}?mode=ro", uri=True, timeout=5) as db:
                row = db.execute(f"SELECT {','.join(COUNTERS)} FROM sessions WHERE id=?", (self.sid,)).fetchone()
        except sqlite3.Error:
            return {}
        return {k: v for k, v in zip(COUNTERS, row or ()) if v is not None}

    def repoint(self):
        """session/load restores the endpoint and model the session was created with; the provider
        URL (a per-session gateway) and model may differ now, so make it take today's."""
        if not os.path.exists(self.db):
            return
        with sqlite3.connect(self.db, timeout=10) as db:
            db.execute("UPDATE sessions SET model_config=json_remove(model_config, '$.base_url'), billing_base_url=NULL,"
                       " model=coalesce(nullif(?, ''), model) WHERE id=? AND json_valid(model_config)", (self.model, self.sid))


if __name__ == "__main__":
    HermesAdapter().main()
