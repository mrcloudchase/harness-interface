"""pi (earendil-works/pi-coding-agent) driven over `pi --mode rpc`: one JSON command per stdin line,
NDJSON events and `response` records on stdout, passed through unchanged.

- provider: pi reads no base-URL env var, so every response rewrites $HOME/.pi/agent/models.json from
  HI_PROVIDER_URL/API. The key is never in pi's env or argv: `apiKey: "!cat <key file>"` makes pi read
  the file (a gateway token or the key) per request. A model in pi's catalog keeps its built-in
  provider (prices, limits); anything else becomes a custom provider `hi` (cost unknown).
- session: the id is ours (uuid) or HI_RESUME; resume by session file (cwd-independent).
- task: `prompt`; steer: `prompt` + streamingBehavior "steer" ("queued" while busy, "started" if idle);
  stop: `clear_queue` (else queued steers outlive the abort) then `abort`;
  done: `agent_settled` with no steer in flight or queued.
"""
import glob
import json
import os
import shlex
import subprocess
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import Adapter, child_env  # noqa: E402

AGENT_DIR = os.path.join(os.environ["HOME"], ".pi", "agent")
# contract API shape -> (pi's built-in provider with a catalog for it, pi's api name)
SHAPES = {"anthropic-messages": ("anthropic", "anthropic-messages"),
          "openai-responses": ("openai", "openai-responses"),
          "openai-chat": (None, "openai-completions")}


def base_url(url: str, api: str) -> str:
    """pi appends /v1/messages (anthropic) or /chat/completions, /responses (openai) to baseUrl."""
    url = url.rstrip("/")
    if api == "anthropic-messages":
        return url[:-3] if url.endswith("/v1") else url
    path = url.split("://", 1)[1].partition("/")[2]
    return url if path else url + "/v1"                 # a bare host means the OpenAI SDK's /v1


def in_catalog(provider: str, model: str) -> bool:
    out = subprocess.run(["pi", "--offline", "--list-models", model], capture_output=True, text=True,
                         timeout=30, env=child_env(), stdin=subprocess.DEVNULL).stdout
    return any(line.split()[:2] == [provider, model] for line in out.splitlines())


def configure(model: str) -> tuple[str, bool]:
    """Write models.json for this response's provider; returns (pi provider name, priced)."""
    path = os.path.join(AGENT_DIR, "models.json")
    try:
        with open(path) as f:
            doc = json.load(f)                          # keep whatever home/ supplied
    except FileNotFoundError:
        doc = {}
    providers = doc.setdefault("providers", {})
    providers.pop("hi", None)
    api = os.environ["HI_PROVIDER_API"]
    builtin, pi_api = SHAPES[api]
    conf = {"baseUrl": base_url(os.environ["HI_PROVIDER_URL"], api),
            "apiKey": "!cat " + shlex.quote(os.environ["HI_PROVIDER_KEY_FILE"])}

    def write():
        os.makedirs(AGENT_DIR, exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump(doc, f, indent=2)
        os.replace(path + ".tmp", path)

    if builtin:
        providers[builtin] = {**providers.get(builtin, {}), **conf}
        write()
        if in_catalog(builtin, model):
            return builtin, True
    providers["hi"] = {**conf, "api": pi_api, "models": [{"id": model}]}
    write()
    return "hi", False


class PiAdapter(Adapter):
    stop_grace_s = 10.0

    def start(self, request):
        model = request["model"] or "claude-sonnet-4-6"
        self.provider, self.priced = configure(model) if os.environ.get("HI_PROVIDER_URL") else ("anthropic", True)
        sid = request["resume"] or str(uuid.uuid4())
        found = glob.glob(os.path.join(AGENT_DIR, "sessions", "*", f"*_{glob.escape(sid)}.jsonl"))
        if request["resume"] and not found:
            self.emit({"type": "hi.warning", "text": f"no saved pi session {sid}; starting it empty"})
        self.out.write(resume=sid)                       # early: the id is ours before pi starts
        self.cli = self.spawn(["pi", "--mode", "rpc", "--provider", self.provider, "--model", model,
                               *(["--session", found[0]] if found else ["--session-id", sid])])
        self.running = self.aborting = False
        self.inflight = self.queued = self.n = 0
        self.usage, self.cost, self.last, self.text = {}, 0.0, {}, ""
        self.send({"id": "hi-state", "type": "get_state"})
        self.send({"id": "hi-task", "type": "prompt", "message": request["task"]})

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
        if kind == "response":
            self.on_response(ev)
        elif kind == "agent_start":
            self.running = True
        elif kind == "queue_update":
            self.queued = len(ev.get("steering") or []) + len(ev.get("followUp") or [])
        elif kind == "message_end" and (ev.get("message") or {}).get("role") == "assistant":
            self.on_assistant(ev["message"])
        elif kind == "agent_settled":
            self.running = False
            self.out.write(answer=self.answer(), usage=self.usage, cost_usd=round(self.cost, 6) if self.priced else None)
            if ev.get("aborted") or self.stopping_since:
                self.finish("stopped")
            elif self.inflight == 0 and self.queued == 0:   # else a steer raced the end: it starts a new run
                self.finish("fail" if self.last.get("stopReason") == "error" else "ok")

    def on_response(self, ev):
        rid, ok, data = ev.get("id") or "", ev.get("success"), ev.get("data") or {}
        if rid == "hi-state" and ok:
            self.out.write(resume=data.get("sessionId") or self.out.data["resume"])
        elif rid == "hi-task" and not ok:
            self.finish("fail", answer=f"pi refused the task: {ev.get('error')}")
        elif rid.startswith("hi-steer-"):
            self.inflight -= 1
            if ok and data.get("disposition") in ("queued", "started"):
                self.accepted_steer()
                self.running = self.running or data["disposition"] == "started"
            elif not self.running and self.queued == 0 and not self.finished:
                self.finish("fail" if self.last.get("stopReason") == "error" else "ok", answer=self.answer())
        elif rid == "hi-abort" and not self.running:      # nothing was running: no agent_settled follows
            self.finish("stopped", answer=self.answer())

    def on_assistant(self, msg):
        self.last = msg
        u = msg.get("usage") or {}
        for ours, theirs in (("input_tokens", "input"), ("output_tokens", "output"),
                             ("cache_read_tokens", "cacheRead"), ("cache_write_tokens", "cacheWrite")):
            self.usage[ours] = self.usage.get(ours, 0) + int(u.get(theirs) or 0)
        self.cost += float((u.get("cost") or {}).get("total") or 0)
        text = "".join(b.get("text", "") for b in msg.get("content") or [] if b.get("type") == "text").strip()
        if text:
            self.text = text
        if msg.get("stopReason") == "error" and not self.stopping_since:   # an abort ends as "error" too
            self.text = f"error: {msg.get('errorMessage', '')}"

    def answer(self):
        return self.text

    def steer(self, text):
        self.inflight += 1
        self.send({"id": f"hi-steer-{self.n}", "type": "prompt", "message": text, "streamingBehavior": "steer"})
        self.n += 1

    def stop(self):
        self.send({"id": "hi-clear", "type": "clear_queue"})
        self.send({"id": "hi-abort", "type": "abort"})


if __name__ == "__main__":
    PiAdapter().main()
