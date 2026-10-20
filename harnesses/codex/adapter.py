"""Codex adapter: `codex app-server`, JSON-RPC 2.0 over stdio, one object per line.

initialize{experimentalApi} -> initialized -> account/login/start{apiKey} -> thread/start | thread/resume -> turn/start
- the key: the RPC login, kept in app-server's memory (`cli_auth_credentials_store = "ephemeral"` in
  config.toml): no auth.json, and it is in no environment the model's shell could inherit;
- the provider: the custom provider `hi` in config.toml, its base_url set here from HI_PROVIDER_URL as
  given (`…/v1`; codex appends `/responses`);
- the thread: approvalPolicy never; sandbox danger-full-access, because the container is the sandbox and
  codex's bwrap cannot create namespaces in it; `bypass_hook_trust`, because the hooks in $CODEX_HOME
  are the folder's own (home/ is copied over them before every response) and codex skips untrusted ones;
- resume: the thread id, written to HI_OUTPUT as soon as thread/start (or thread/resume) answers;
- steer: turn/steer{expectedTurnId}; one that comes before the turn id, or is refused because the turn
  just ended, is queued and started as the next turn;
- done: turn/completed for our turn, with no steer queued or in flight; stop: turn/interrupt, then the
  turn/completed `interrupted` that follows;
- usage: thread/tokenUsage/updated `total` is cumulative over the thread, so a response's usage is the
  total less what it was before the response's first model call (`total - last` of the first update).
  `input_tokens` leaves out cache reads (`cache_read_tokens`), as Anthropic's does; cost: codex has none.
Every app-server message goes to stdout unchanged.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import USAGE, Adapter, JsonRpc, provider_key  # noqa: E402

# Requests from app-server. approvalPolicy "never" means none should come; any that does is accepted.
APPROVALS = {"item/commandExecution/requestApproval": {"decision": "accept"},
             "item/fileChange/requestApproval": {"decision": "accept"},
             "execCommandApproval": {"decision": "approved"}, "applyPatchApproval": {"decision": "approved"}}


def usage_of(total, base):
    """Codex's token counts, less `base`, in the contract's five keys."""
    d = {k: v - base.get(k, 0) for k, v in total.items() if isinstance(v, int)}
    cached = d.get("cachedInputTokens", 0)
    return {"input_tokens": d.get("inputTokens", 0) - cached, "output_tokens": d.get("outputTokens", 0),
            "cache_read_tokens": cached, "cache_write_tokens": d.get("cacheWriteInputTokens", 0),
            "reasoning_tokens": d.get("reasoningOutputTokens", 0)}


class CodexAdapter(Adapter):
    stop_grace_s = 15.0

    def start(self, request):
        url = os.environ.get("HI_PROVIDER_URL", "")
        assert url, "codex needs a provider (HI_PROVIDER_URL)"
        assert os.environ.get("HI_PROVIDER_API") == "openai-responses", "codex speaks openai-responses only"
        self.request = request
        self.thread = self.turn = self.last_turn = None   # ids; turn is None while idle
        self.turn_starting = False                         # turn/start sent, its id not yet known
        self.my_turns, self.pending, self.steers_in_flight = set(), [], 0
        self.base = None
        self.out.write(usage=dict.fromkeys(USAGE, 0))
        self.cli = self.spawn(["codex", "app-server", "-c", f'model_providers.hi.base_url="{url}"'])
        self.rpc = JsonRpc(self.cli, answer=lambda method, _params: APPROVALS.get(method, {}))
        self.rpc.call("initialize", {"clientInfo": {"name": "harness-interface", "version": "1"},
                                     "capabilities": {"experimentalApi": True}}, self.on_initialized)

    def failed(self, what, error):
        self.finish("fail", answer=f"{what}: {error.get('message', error)}")

    # --- the start chain -----------------------------------------------------------------------
    def on_initialized(self, _result, error):
        if error:
            return self.failed("initialize", error)
        self.rpc.notify("initialized")
        self.rpc.call("account/login/start", {"type": "apiKey", "apiKey": provider_key()}, self.on_login)

    def on_login(self, _result, error):
        if error:
            return self.failed("login", error)
        r = self.request
        opts = {"cwd": os.environ["HI_WORKSPACE"], "approvalPolicy": "never", "sandbox": "danger-full-access",
                "config": {"bypass_hook_trust": True}}
        if r["model"]:
            opts["model"] = r["model"]
        if r["resume"]:
            self.rpc.call("thread/resume", {"threadId": r["resume"], **opts}, self.on_thread)
        else:
            self.rpc.call("thread/start", opts, self.on_thread)

    def on_thread(self, result, error):
        if error:
            return self.failed("thread", error)
        self.thread = result["thread"]["id"]
        self.out.write(resume=self.thread)
        if self.stopping:                                  # stopped before any turn began
            return self.finish("stopped")
        self.start_turn(self.request["task"], steers=0)

    def start_turn(self, text, steers):
        self.turn_starting = True
        self.rpc.call("turn/start", {"threadId": self.thread, "input": [{"type": "text", "text": text}]},
                      lambda result, error: self.on_turn(result, error, steers))

    def on_turn(self, result, error, steers):
        self.turn_starting = False
        if error:
            return self.failed("turn/start", error)
        self.turn = result["turn"]["id"]
        self.my_turns.add(self.turn)
        for _ in range(steers):
            self.accepted_steer()
        if self.stopping:
            return self.interrupt()
        queued, self.pending = self.pending, []
        for text in queued:                                # steers that came before the turn id
            self.steer(text)

    # --- events --------------------------------------------------------------------------------
    def on_line(self, source, line):
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return self.emit({"type": "hi.text", "text": line})
        self.emit(msg)
        if not self.rpc.dispatch(msg):
            return
        method, p = msg.get("method"), msg.get("params") or {}
        if method == "item/completed" and (p.get("item") or {}).get("type") == "agentMessage":
            self.out.write(answer=p["item"].get("text") or "")
        elif method == "thread/tokenUsage/updated" and p.get("turnId") in self.my_turns:
            usage = p.get("tokenUsage") or {}
            total, last = usage.get("total") or {}, usage.get("last") or {}
            if self.base is None:
                self.base = {k: v - last.get(k, 0) for k, v in total.items() if isinstance(v, int)}
            self.out.write(usage=usage_of(total, self.base))
        elif method == "turn/completed" and (p.get("turn") or {}).get("id") == self.turn:
            self.turn, self.last_turn = None, p["turn"]
            self.maybe_done()

    def maybe_done(self):
        if self.turn or self.turn_starting or self.steers_in_flight:
            return
        if self.pending and not self.stopping:            # a steer that raced the turn's end: the next turn
            queued, self.pending = self.pending, []
            return self.start_turn("\n\n".join(queued), steers=len(queued))
        t = self.last_turn
        if t["status"] == "completed":
            self.finish("ok")
        elif t["status"] == "interrupted":
            self.finish("stopped" if self.stopping else "fail")
        else:
            err = t.get("error") or {}
            self.finish("fail", answer=self.out.data["answer"] or f"turn {t['status']}: {err.get('message', err)}")

    # --- steer and stop ------------------------------------------------------------------------
    def steer(self, text):
        if not self.turn:                                  # not started yet, or just ended: queue it
            return self.pending.append(text)
        self.steers_in_flight += 1
        self.rpc.call("turn/steer", {"threadId": self.thread, "expectedTurnId": self.turn,
                                     "input": [{"type": "text", "text": text}]},
                      lambda _result, error: self.on_steer(text, error))

    def on_steer(self, text, error):
        self.steers_in_flight -= 1
        if error:                                          # the turn ended under it: run it next
            self.pending.append(text)
        else:
            self.accepted_steer()
        self.maybe_done()

    def stop(self):
        if self.turn:
            self.interrupt()
        elif self.thread and not self.turn_starting:       # between turns, waiting on a steer's reply
            self.finish("stopped")
        # else on_thread or on_turn sees the stop and acts on it

    def interrupt(self):
        self.rpc.call("turn/interrupt", {"threadId": self.thread, "turnId": self.turn})


if __name__ == "__main__":
    CodexAdapter().main()
