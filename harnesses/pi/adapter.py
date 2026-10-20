"""pi adapter: `pi --mode rpc`, one JSON command per stdin line; pi's events and `response` records on
stdout, passed through unchanged.

- provider: pi reads no base-URL variable, so every response writes $HOME/.pi/agent/models.json: the
  folder's own (home/, if it ships one), plus HI_PROVIDER_URL as given and
  `apiKey: "!cat <HI_PROVIDER_KEY_FILE>"`, a command pi runs for each request, so the key (or, under the
  gateway, the session's token) is never in pi's environment, argv or files. A model in pi's catalog
  under the shape's built-in provider (anthropic, openai) keeps the catalog's limits and prices; any
  other runs as the custom provider `hi`, with no price (cost null);
- resume: the session id, ours (a uuid) and written to HI_OUTPUT before pi starts; a resumed session
  opens by its file, which works from any cwd;
- task: `prompt`; steer: `prompt` with streamingBehavior "steer" (`queued` while pi works, `started`
  when it is idle); pi delivers it after the current batch of tool calls, before the next model call;
- stop: `clear_queue` (else queued steers outlive the abort), then `abort`;
- done: `agent_settled` with no steer unanswered or queued;
- an extension's dialog (confirm, select, input, editor) is cancelled at once: nobody is there to answer;
- usage: the sum over this response's assistant messages, in the five contract keys.
The config artifacts show in pi's own events: the system message lists the skills and every tool
declared (MCP tools among them); an extension's notifications arrive as `extension_ui_request`.
"""
import glob
import json
import os
import shlex
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import USAGE, Adapter, child_env  # noqa: E402

AGENT_DIR = os.path.join(os.environ.get("HOME", "."), ".pi", "agent")
SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "home", ".pi", "agent", "models.json")
# the contract's shape -> (pi's built-in provider for it, with a catalog; pi's name for the API)
SHAPES = {"anthropic-messages": ("anthropic", "anthropic-messages"),
          "openai-responses": ("openai", "openai-responses"),
          "openai-chat": (None, "openai-completions")}
DEFAULT_MODEL = {"anthropic-messages": "claude-sonnet-4-6", "openai-responses": "gpt-5-mini"}
FROM_USAGE = {"input": "input_tokens", "output": "output_tokens", "cacheRead": "cache_read_tokens",
              "cacheWrite": "cache_write_tokens", "reasoning": "reasoning_tokens"}
DIALOGS = ("select", "confirm", "input", "editor")


def in_catalog(provider: str, model: str) -> bool:
    out = subprocess.run(["pi", "--offline", "--list-models", model], capture_output=True, text=True,
                         timeout=60, env=child_env(), stdin=subprocess.DEVNULL).stdout
    return any(line.split()[:2] == [provider, model] for line in out.splitlines())


def configure(api: str, model: str) -> tuple[str, bool]:
    """Write models.json for this response's provider; returns (pi's provider name, priced)."""
    try:
        with open(SHIPPED) as f:
            doc = json.load(f)
    except FileNotFoundError:
        doc = {}
    providers = doc.setdefault("providers", {})
    builtin, pi_api = SHAPES[api]
    conf = {"baseUrl": os.environ["HI_PROVIDER_URL"],
            "apiKey": "!cat " + shlex.quote(os.environ["HI_PROVIDER_KEY_FILE"])}
    if builtin:
        providers[builtin] = {**providers.get(builtin, {}), **conf}
    providers["hi"] = {**conf, "api": pi_api, "models": [{"id": model}]}
    os.makedirs(AGENT_DIR, exist_ok=True)
    path = os.path.join(AGENT_DIR, "models.json")
    with open(path + ".tmp", "w") as f:
        json.dump(doc, f, indent=2)
    os.replace(path + ".tmp", path)
    return (builtin, True) if builtin and in_catalog(builtin, model) else ("hi", False)


class PiAdapter(Adapter):
    stop_grace_s = 10.0

    def start(self, request):
        api = os.environ.get("HI_PROVIDER_API", "anthropic-messages")
        model = request["model"] or DEFAULT_MODEL.get(api)
        if not model:
            return self.finish("fail", answer=f"pi has no default model for {api}: name one")
        argv = ["pi", "--mode", "rpc", "--model", model]
        self.priced = True
        if os.environ.get("HI_PROVIDER_URL"):
            provider, self.priced = configure(api, model)
            argv += ["--provider", provider]
        sid = request["resume"] or str(uuid.uuid4())
        found = glob.glob(os.path.join(AGENT_DIR, "sessions", "*", f"*_{glob.escape(sid)}.jsonl"))
        if request["resume"] and not found:
            self.emit({"type": "hi.warning", "text": f"no saved pi session {sid}; starting it empty"})
        self.out.write(resume=sid)                       # early: the id is ours before pi starts
        self.cli = self.spawn(argv + (["--session", found[0]] if found else ["--session-id", sid]))
        self.running = False
        self.unanswered = self.queued = self.n = 0
        self.usage, self.cost, self.last, self.text = dict.fromkeys(USAGE, 0), 0.0, {}, ""
        self.send({"id": "hi-task", "type": "prompt", "message": request["task"]})

    def send(self, cmd):
        self.cli.stdin.write(json.dumps(cmd) + "\n")
        self.cli.stdin.flush()

    def on_line(self, source, line):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return self.emit({"type": "hi.text", "text": line})
        self.emit(ev)                                    # pi's own records, unchanged
        kind = ev.get("type")
        if kind == "response":
            self.on_response(ev)
        elif kind == "extension_ui_request" and ev.get("method") in DIALOGS:
            self.send({"type": "extension_ui_response", "id": ev.get("id"), "cancelled": True})
        elif kind == "agent_start":
            self.running = True
        elif kind == "queue_update":
            self.queued = len(ev.get("steering") or []) + len(ev.get("followUp") or [])
        elif kind == "message_end" and (ev.get("message") or {}).get("role") == "assistant":
            self.on_assistant(ev["message"])
        elif kind == "agent_settled":
            self.running = False
            self.out.write(answer=self.text, usage=self.usage, cost_usd=round(self.cost, 6) if self.priced else None)
            if ev.get("aborted") or self.stopping:
                self.finish("stopped")
            elif self.unanswered == 0 and self.queued == 0:   # else a steer raced the end: it starts a new run
                self.finish(self.outcome())

    def on_response(self, ev):
        rid, ok, data = ev.get("id") or "", ev.get("success"), ev.get("data") or {}
        if rid == "hi-task" and not ok:
            self.finish("fail", answer=f"pi refused the task: {ev.get('error')}")
        elif rid.startswith("hi-steer-"):
            self.unanswered -= 1
            if ok and data.get("disposition") in ("queued", "started"):
                self.accepted_steer()
                self.running = self.running or data["disposition"] == "started"
            elif not self.running and self.queued == 0:
                self.finish(self.outcome(), answer=self.text)
        elif rid == "hi-abort" and not self.running:      # nothing was running: no agent_settled follows
            self.finish("stopped", answer=self.text)

    def on_assistant(self, msg):
        self.last = msg
        u = msg.get("usage") or {}
        for theirs, ours in FROM_USAGE.items():
            self.usage[ours] += int(u.get(theirs) or 0)
        self.cost += float((u.get("cost") or {}).get("total") or 0)
        text = "".join(b.get("text", "") for b in msg.get("content") or [] if b.get("type") == "text").strip()
        if text:
            self.text = text
        if msg.get("stopReason") == "error" and not self.stopping:   # an abort can end as "error" too
            self.text = f"error: {msg.get('errorMessage', '')}"

    def outcome(self):
        return "fail" if self.last.get("stopReason") == "error" else "ok"

    def steer(self, text):
        self.unanswered += 1
        self.send({"id": f"hi-steer-{self.n}", "type": "prompt", "message": text, "streamingBehavior": "steer"})
        self.n += 1

    def stop(self):
        self.send({"id": "hi-clear", "type": "clear_queue"})
        self.send({"id": "hi-abort", "type": "abort"})


if __name__ == "__main__":
    PiAdapter().main()
