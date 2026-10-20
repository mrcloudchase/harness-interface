"""Codex over `codex app-server` (JSON-RPC 2.0, one object per line on stdio).

initialize{experimentalApi} -> initialized -> account/login/start{apiKey} (ephemeral store: no auth.json)
-> thread/start | thread/resume (approvalPolicy never, sandbox danger-full-access: the container is the
sandbox, codex's bwrap cannot run in it) -> turn/start. A steer while a turn runs is turn/steer
{threadId, expectedTurnId, input}; refused ("no active turn") or idle, it is queued and started as the
next turn. Stop = turn/interrupt. Done = turn/completed for our turn with no steer queued or in flight.
Every app-server message (notifications and our replies) goes to stdout unchanged."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import Adapter, provider_key  # noqa: E402

# Server -> client requests. approvalPolicy "never" should mean none arrive; answer any that do.
APPROVALS = {"item/commandExecution/requestApproval": {"decision": "accept"},
             "item/fileChange/requestApproval": {"decision": "accept"},
             "execCommandApproval": {"decision": "approved"}, "applyPatchApproval": {"decision": "approved"}}


class CodexAdapter(Adapter):
    stop_grace_s = 10.0

    def start(self, request):
        url = os.environ.get("HI_PROVIDER_URL", "").rstrip("/")
        assert url, "codex needs a provider (HI_PROVIDER_URL)"
        assert os.environ.get("HI_PROVIDER_API") == "openai-responses", "codex speaks openai-responses only"
        self.request, self.next_id, self.replies = request, 0, {}
        self.thread = self.turn = self.last_turn = None   # ids; turn is None while idle
        self.turn_starting = False           # turn/start sent, id not yet known
        self.my_turns, self.pending, self.steers_in_flight = set(), [], 0
        self.usage_base, self.usage = None, {}
        self.cli = self.spawn(["codex", "app-server", "-c", f'model_providers.hi.base_url="{url}"'])
        self.call("initialize", {"clientInfo": {"name": "harness-interface", "version": "1"},
                                 "capabilities": {"experimentalApi": True}}, self.on_initialized)

    # --- JSON-RPC ------------------------------------------------------------------------------
    def send(self, obj):
        self.cli.stdin.write(json.dumps({"jsonrpc": "2.0", **obj}) + "\n")
        self.cli.stdin.flush()

    def call(self, method, params, then):
        """Send a request; then(result, error) runs when its reply line arrives."""
        self.next_id += 1
        self.replies[self.next_id] = then
        self.send({"id": self.next_id, "method": method, "params": params})

    def fail_on(self, what, error):
        self.finish("fail", answer=f"{what}: {error.get('message', error)}")

    # --- the start chain -----------------------------------------------------------------------
    def on_initialized(self, _result, error):
        if error:
            return self.fail_on("initialize", error)
        self.send({"method": "initialized"})
        self.call("account/login/start", {"type": "apiKey", "apiKey": provider_key()}, self.on_login)

    def on_login(self, _result, error):
        if error:
            return self.fail_on("login", error)
        r = self.request
        opts = {"cwd": os.environ["HI_WORKSPACE"], "approvalPolicy": "never", "sandbox": "danger-full-access"}
        if r["model"]:
            opts["model"] = r["model"]
        if r["resume"]:
            self.call("thread/resume", {"threadId": r["resume"], **opts}, self.on_thread)
        else:
            self.call("thread/start", opts, self.on_thread)

    def on_thread(self, result, error):
        if error:
            return self.fail_on("thread", error)
        self.thread = result["thread"]["id"]
        self.out.write(resume=self.thread)                   # early: the resume id is known
        if self.stopping_since:                               # stopped before any turn began
            return self.finish("stopped")
        self.start_turn(self.request["task"], steers=0)

    def start_turn(self, text, steers):
        self.turn_starting = True
        self.call("turn/start", {"threadId": self.thread, "input": [{"type": "text", "text": text}]},
                  lambda res, err: self.on_turn(res, err, steers))

    def on_turn(self, result, error, steers):
        self.turn_starting = False
        if error:
            return self.fail_on("turn/start", error)
        self.turn = result["turn"]["id"]
        self.my_turns.add(self.turn)
        for _ in range(steers):
            self.accepted_steer()
        if self.stopping_since:
            return self.interrupt()
        queued, self.pending = self.pending, []
        for text in queued:                                   # steers that came before the turn id
            self.steer(text)

    # --- events --------------------------------------------------------------------------------
    def on_line(self, source, line):
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return self.emit({"type": "hi.text", "text": line})
        self.emit(msg)
        if "id" in msg and "method" in msg:                   # a server request
            return self.send({"id": msg["id"], "result": APPROVALS.get(msg["method"], {})})
        if "id" in msg:                                       # a reply to one of ours
            then = self.replies.pop(msg["id"], None)
            return then and then(msg.get("result"), msg.get("error"))
        method, p = msg.get("method"), msg.get("params", {})
        if method == "item/completed" and p.get("item", {}).get("type") == "agentMessage":
            self.out.write(answer=p["item"].get("text") or "")
        elif method == "thread/tokenUsage/updated":
            self.on_usage(p)
        elif method == "turn/completed" and p.get("turn", {}).get("id") == self.turn:
            self.turn, self.last_turn = None, p["turn"]
            self.maybe_done()

    def on_usage(self, p):
        """`total` is cumulative over the thread: per response = total - the total before our first turn."""
        total = p.get("tokenUsage", {}).get("total") or {}
        if p.get("turnId") not in self.my_turns:
            self.usage_base = total
            return
        base = self.usage_base or {}
        self.usage = {k: v - base.get(k, 0) for k, v in total.items() if isinstance(v, int)}
        self.out.write(usage=self.usage)

    def maybe_done(self):
        if self.turn or self.turn_starting or self.steers_in_flight:
            return
        t = self.last_turn
        if self.pending and not self.stopping_since:          # a steer that raced the end: next turn
            queued, self.pending = self.pending, []
            return self.start_turn("\n\n".join(queued), steers=len(queued))
        if t["status"] == "completed":
            self.finish("ok")
        elif t["status"] == "interrupted":
            self.finish("stopped" if self.stopping_since else "fail")
        else:
            err = t.get("error") or {}
            self.finish("fail", answer=self.out.data["answer"] or f"turn {t['status']}: {err.get('message', err)}")

    # --- steer and stop ------------------------------------------------------------------------
    def steer(self, text):
        if not self.turn:                 # not started yet, or ended with a steer reply pending: queue it
            return self.pending.append(text)
        self.steers_in_flight += 1
        self.call("turn/steer", {"threadId": self.thread, "expectedTurnId": self.turn,
                                 "input": [{"type": "text", "text": text}]},
                  lambda res, err: self.on_steer(text, err))

    def on_steer(self, text, error):
        self.steers_in_flight -= 1
        if error:                                             # the turn ended under it: run it next
            self.pending.append(text)
        else:
            self.accepted_steer()
        self.maybe_done()

    def stop(self):
        if self.turn:
            self.interrupt()
        elif self.thread and not self.turn_starting:          # between turns, waiting on a steer reply
            self.finish("stopped")
        # else on_thread / on_turn see stopping_since and stop there

    def interrupt(self):
        self.call("turn/interrupt", {"threadId": self.thread, "turnId": self.turn}, lambda res, err: None)


if __name__ == "__main__":
    CodexAdapter().main()
