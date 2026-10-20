"""OpenCode adapter (pattern P4: a local HTTP server inside the run).

`opencode serve` on 127.0.0.1 (own session) -> wait for "listening" (a request sent earlier can hang
forever) -> POST /session (or reuse HI_RESUME) -> subscribe GET /event (SSE) -> once it says
server.connected, POST prompt_async with the task. A steer is the same call while busy: OpenCode
queues it and its loop takes it at the next step. Done = session.status idle with every prompt we
sent answered. Stop = POST /abort, then idle. SSE parts are re-emitted as the NDJSON events of
`opencode run --format json` (step_start, text, tool_use, step_finish, reasoning, error), plus
{"type":"session"} and {"type":"user"} (a prompt OpenCode accepted)."""
import base64
import json
import os
import secrets
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import Adapter, child_env  # noqa: E402

# HI_PROVIDER_API -> OpenCode provider id and its config (npm = the bundled AI SDK package)
PROVIDERS = {"anthropic-messages": ("anthropic", {}), "openai-responses": ("openai", {}),
             "openai-chat": ("hi", {"npm": "@ai-sdk/openai-compatible", "name": "hi"})}
RUN_EVENT = {"step-start": "step_start", "step-finish": "step_finish", "text": "text", "reasoning": "reasoning"}


def provider_config(model: str) -> tuple[str, dict]:
    """(providerID, config) for OPENCODE_CONFIG_CONTENT: base URL with OpenCode's /v1 rule, the key
    as a {file:…} reference (OpenCode reads it itself; the value is in no environment), the model
    declared so ids missing from the built-in catalog work, small_model = the same model so title
    generation calls nothing else."""
    pid, extra = PROVIDERS[os.environ["HI_PROVIDER_API"]]
    url = os.environ["HI_PROVIDER_URL"].rstrip("/")
    key_file = os.environ.get("HI_PROVIDER_KEY_FILE")
    options = {"baseURL": url if url.endswith("/v1") else url + "/v1",
               "apiKey": f"{{file:{key_file}}}" if key_file else "{env:HI_PROVIDER_KEY}"}
    config = {"enabled_providers": [pid], "model": f"{pid}/{model}", "small_model": f"{pid}/{model}",
              "provider": {pid: {**extra, "options": options, "models": {model: {}}}}}
    return pid, config


class OpenCodeAdapter(Adapter):
    stop_grace_s = 10.0

    def start(self, request):
        self.ws = os.environ["HI_WORKSPACE"]
        self.query = "?directory=" + urllib.parse.quote(self.ws, safe="")
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # loopback: never proxied
        self.model = request["model"]
        password = secrets.token_hex(16)                       # loopback is shared on a host: basic auth
        self.auth = {"authorization": "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()}
        env = child_env(PWD=self.ws, OPENCODE_SERVER_PASSWORD=password)
        self.provider = "anthropic"
        if os.environ.get("HI_PROVIDER_URL"):
            self.provider, config = provider_config(self.model)
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        self.task = request["task"]           # instructions: ~/.config/opencode/AGENTS.md (harness.json files)
        self.sid, self.base, self.prompted = request["resume"], None, False
        self.started_ms = int(time.time() * 1000)
        self.pending: list[str] = []          # steers that arrived before the task was sent
        self.sent = 0                         # prompts sent (task + steers)
        self.users: list[str] = []            # user message ids accepted in this response
        self.assistants: list[str] = []       # assistant message ids of this response
        self.texts: dict[str, list[str]] = {}
        self.seen: set = set()
        self.busy, self.error, self.aborted = False, None, False
        self.usage = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
                      "cache_read_tokens": 0, "cache_write_tokens": 0}
        self.cost = 0.0
        self.server = self.spawn(["opencode", "serve", "--port", "0", "--hostname", "127.0.0.1"], name="server",
                                 stdin=subprocess.DEVNULL, env=env)

    # --- HTTP to the local server ------------------------------------------------------------------
    def call(self, method: str, path: str, body=None):
        req = urllib.request.Request(self.base + path + self.query, method=method,
                                     headers={"content-type": "application/json", **self.auth},
                                     data=None if body is None else json.dumps(body).encode())
        with self.http.open(req, timeout=30) as r:
            text = r.read().decode()
        return json.loads(text) if text.strip() else None

    def prompt(self, text: str) -> None:
        self.sent += 1
        self.call("POST", f"/session/{self.sid}/prompt_async",
                  {"model": {"providerID": self.provider, "modelID": self.model}, "parts": [{"type": "text", "text": text}]})

    def subscribe(self) -> None:
        resp = self.http.open(urllib.request.Request(self.base + "/event" + self.query, headers=self.auth), timeout=None)

        def pump():
            for raw in resp:
                line = raw.decode().strip()
                if line.startswith("data:"):
                    self.events.put(("sse", line[5:].strip()))
        threading.Thread(target=pump, daemon=True).start()

    def ready(self) -> None:
        if self.sid:
            try:
                self.call("GET", f"/session/{self.sid}")
            except urllib.error.HTTPError as e:
                return self.finish("fail", answer=f"cannot resume {self.sid}: HTTP {e.code}")
        else:
            self.sid = self.call("POST", "/session", {"title": "hi"})["id"]   # a set title: no title-generation call
        self.out.write(resume=self.sid)                          # early: before any model call
        self.emit({"type": "session", "sessionID": self.sid})
        self.subscribe()                                         # before prompting
        if self.stopping_since:
            self.finish("stopped")

    # --- the four contract methods -----------------------------------------------------------------
    def on_line(self, source, line):
        if source == "server":
            m = re.search(r"listening on (http://\S+)", line)
            if m and not self.base:
                self.base = m.group(1)
                return self.ready()
            return print(f"opencode: {line}", file=sys.stderr, flush=True)
        ev = json.loads(line)
        kind, p = ev.get("type"), ev.get("properties") or {}
        if kind == "server.connected" and not self.prompted:
            self.prompted = True
            for text in [self.task, *self.pending]:
                self.prompt(text)
            self.pending = []
        elif kind == "message.updated":
            self.on_message(p.get("info") or {})
        elif kind == "message.part.updated":
            self.on_part(p.get("part") or {})
        elif kind == "session.error" and p.get("sessionID") == self.sid:
            err = p.get("error") or {}
            self.emit({"type": "error", "sessionID": self.sid, "error": err})
            if err.get("name") == "MessageAbortedError":
                self.aborted = True
            else:
                self.error = err
        elif kind == "session.status" and p.get("sessionID") == self.sid:
            status = p.get("status") or {}
            if status.get("type") == "busy":
                self.busy = True
            elif status.get("type") == "retry":
                self.emit({"type": "retry", "sessionID": self.sid, "status": status})
            elif status.get("type") == "idle" and self.busy:
                self.on_idle()
        elif kind == "permission.asked" and p.get("sessionID") == self.sid:    # config allows all; never hang
            self.call("POST", f"/permission/{p['id']}/reply", {"reply": "once"})
        elif kind == "question.asked" and p.get("sessionID") == self.sid:
            self.call("POST", f"/question/{p['id']}/reject", {})

    def on_message(self, info: dict) -> None:
        if info.get("sessionID") != self.sid or (info.get("time") or {}).get("created", 0) < self.started_ms:
            return
        mid = info["id"]
        if info.get("role") == "user" and mid not in self.users:
            self.users.append(mid)
            self.emit({"type": "user", "sessionID": self.sid, "messageID": mid})
            if len(self.users) > 1:
                self.accepted_steer()
        elif info.get("role") == "assistant" and mid not in self.assistants:
            self.assistants.append(mid)

    def on_part(self, part: dict) -> None:
        if part.get("sessionID") != self.sid or part.get("messageID") in self.users:
            return
        kind, state = part.get("type"), part.get("state") or {}
        name = RUN_EVENT.get(kind)
        if kind == "tool" and state.get("status") in ("completed", "error"):
            name = "tool_use"
        if kind in ("text", "reasoning") and not (part.get("time") or {}).get("end"):
            name = None                                           # still streaming
        if not name or (part["id"], name) in self.seen:
            return
        self.seen.add((part["id"], name))
        self.emit({"type": name, "timestamp": int(time.time() * 1000), "sessionID": self.sid, "part": part})
        if name == "text" and part.get("text") and not part.get("synthetic"):
            self.texts.setdefault(part["messageID"], []).append(part["text"])
        elif name == "step_finish":
            t = part.get("tokens") or {}
            for k, v in (("input_tokens", t.get("input")), ("output_tokens", t.get("output")),
                         ("reasoning_tokens", t.get("reasoning")), ("cache_read_tokens", (t.get("cache") or {}).get("read")),
                         ("cache_write_tokens", (t.get("cache") or {}).get("write"))):
                self.usage[k] += v or 0
            self.cost += part.get("cost") or 0.0
            self.out.write(answer=self.answer(), usage=self.usage, cost_usd=round(self.cost, 6))

    def answer(self) -> str:
        for mid in reversed(self.assistants):
            if self.texts.get(mid):
                return "\n".join(self.texts[mid])
        return ""

    def on_idle(self) -> None:
        fields = {"answer": self.answer(), "usage": self.usage, "cost_usd": round(self.cost, 6)}
        if self.stopping_since or self.aborted:
            return self.finish("stopped", **fields)
        if self.error:
            data = self.error.get("data") or {}
            return self.finish("fail", **{**fields, "answer": fields["answer"] or f"{self.error.get('name')}: {data.get('message', '')}"})
        unanswered = self.sent > len(self.users) or (self.users and (not self.assistants or self.users[-1] > self.assistants[-1]))
        if not unanswered:
            self.finish("ok", **fields)
        # else: a prompt is still on its way into OpenCode's loop; the next busy -> idle finishes

    def steer(self, text):
        if self.prompted:
            self.prompt(text)
        else:
            self.pending.append(text)

    def stop(self):
        if not self.prompted:                                     # nothing running yet
            return self.finish("stopped")
        self.call("POST", f"/session/{self.sid}/abort", {})

    def finish(self, status, **fields):
        super().finish(status, **fields)
        try:
            os.killpg(self.server.pid, signal.SIGTERM)            # let it close its database; _reap kills
        except (ProcessLookupError, PermissionError):
            pass


if __name__ == "__main__":
    OpenCodeAdapter().main()
