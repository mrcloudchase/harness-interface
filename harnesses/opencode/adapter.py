"""OpenCode adapter: its own HTTP server on loopback, driven over REST and its SSE event stream.

- `opencode serve --port 0 --hostname 127.0.0.1` in its own session, behind basic auth (a random
  password: loopback is shared on a host); nothing is sent before it prints "listening" (a request sent
  earlier can hang forever);
- the provider is per request, so it goes in OPENCODE_CONFIG_CONTENT: the provider id for
  HI_PROVIDER_API, the base URL as that provider's SDK takes it (@ai-sdk/anthropic wants the `/v1` the
  contract's URL leaves out; the OpenAI shapes take the contract's URL as it is), the key as a
  `{file:…}` reference that OpenCode reads itself, the model declared (ids outside its catalog work) and
  used as the small model too;
- `POST /session` with a preset title (no title-generation call), or `GET /session/{id}` on resume; the
  id goes to HI_OUTPUT before any model call; then what it loaded (its skills, and its MCP servers with their
  status) as one `hi.loaded` event;
- the task and every steer are a `prompt_async` each, sent once the SSE stream says server.connected;
  OpenCode queues a steer and its loop takes it at the next step;
- done = the session goes idle with every prompt sent answered; stop = `POST /session/{id}/abort`, and
  the idle after it ends the response `stopped`;
- stdout: the SSE parts as the NDJSON events of `opencode run --format json` (step_start, text,
  tool_use, step_finish, reasoning, error), plus `session`, `user` (a prompt OpenCode took: the steer's
  acknowledgement), `retry`, `hi.loaded`, and the server's own output lines as `hi.text`;
- usage and cost: the sums over this response's step_finish parts; cost is null when it is 0 for tokens
  spent, which is OpenCode's figure for a model its catalog has no price for.
"""
import base64
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hi_adapter import USAGE, Adapter, child_env  # noqa: E402

# HI_PROVIDER_API -> (OpenCode provider id, its config, what its SDK's base URL adds to the contract's)
PROVIDERS = {"anthropic-messages": ("anthropic", {}, "/v1"),
             "openai-responses": ("openai", {}, ""),
             "openai-chat": ("hi", {"npm": "@ai-sdk/openai-compatible", "name": "hi"}, "")}
RUN_EVENT = {"step-start": "step_start", "step-finish": "step_finish", "text": "text", "reasoning": "reasoning"}
TOKENS = {"input_tokens": ("input",), "output_tokens": ("output",), "reasoning_tokens": ("reasoning",),
          "cache_read_tokens": ("cache", "read"), "cache_write_tokens": ("cache", "write")}


def provider_config(model: str) -> tuple[str, dict]:
    """(provider id, config) for the request's provider and model."""
    pid, extra, suffix = PROVIDERS[os.environ["HI_PROVIDER_API"]]
    options = {"baseURL": os.environ["HI_PROVIDER_URL"].rstrip("/") + suffix,
               "apiKey": "{file:%s}" % os.environ["HI_PROVIDER_KEY_FILE"]}
    config = {"enabled_providers": [pid], "provider": {pid: {**extra, "options": options}}}
    if model:
        config["provider"][pid]["models"] = {model: {}}
        config.update(model=f"{pid}/{model}", small_model=f"{pid}/{model}")
    return pid, config


class Refused(Exception):
    """The server answered a request with an error."""


def sse(response):
    """The data lines of an event stream."""
    for raw in response:
        line = raw.decode().strip()
        if line.startswith("data:"):
            yield line[5:].strip()


def dig(d: dict, path: tuple):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
    return d


class OpenCodeAdapter(Adapter):
    stop_grace_s = 10.0

    def start(self, request):
        self.ws = os.environ["HI_WORKSPACE"]
        self.query = "?directory=" + urllib.parse.quote(self.ws, safe="")
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # loopback: never proxied
        password = secrets.token_hex(16)
        self.auth = {"authorization": "Basic " + base64.b64encode(f"opencode:{password}".encode()).decode()}
        env = child_env(PWD=self.ws, OPENCODE_SERVER_PASSWORD=password)
        self.model, self.provider = request["model"], None
        if os.environ.get("HI_PROVIDER_URL"):
            self.provider, config = provider_config(self.model)
            env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
        self.task, self.sid, self.base, self.prompted = request["task"], request["resume"], None, False
        self.started_ms = int(time.time() * 1000)
        self.pending: list[str] = []          # steers that arrived before the task was sent
        self.sent = 0                         # prompts sent (task + steers)
        self.users: list[str] = []            # user message ids OpenCode took in this response
        self.assistants: list[str] = []       # assistant message ids of this response
        self.texts: dict[str, list[str]] = {}
        self.seen: set = set()
        self.busy, self.error, self.aborted = False, None, False
        self.usage, self.cost = dict.fromkeys(USAGE, 0), 0.0
        self.server = self.spawn(["opencode", "serve", "--port", "0", "--hostname", "127.0.0.1"], name="server",
                                 stdin=subprocess.DEVNULL, env=env)

    def call(self, method: str, path: str, body=None):
        """One request to the server; a refusal raises with what the server said."""
        req = urllib.request.Request(self.base + path + self.query, method=method,
                                     headers={"content-type": "application/json", **self.auth},
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with self.http.open(req, timeout=30) as r:
                text = r.read().decode()
        except urllib.error.HTTPError as e:
            raise Refused(f"{method} {path}: HTTP {e.code} {e.read().decode(errors='replace')[:500]}") from None
        return json.loads(text) if text.strip() else None

    def prompt(self, text: str) -> None:
        self.sent += 1
        body = {"parts": [{"type": "text", "text": text}]}
        if self.provider and self.model:
            body["model"] = {"providerID": self.provider, "modelID": self.model}
        self.call("POST", f"/session/{self.sid}/prompt_async", body)

    def ready(self) -> None:
        """The server listens: the session, what it loaded, then the event stream (before any prompt)."""
        if self.sid:
            try:
                self.call("GET", f"/session/{self.sid}")
            except Refused as e:
                return self.finish("fail", answer=f"cannot resume {self.sid}: {e}")
        else:
            self.sid = self.call("POST", "/session", {"title": "hi"})["id"]
        self.out.write(resume=self.sid)
        self.emit({"type": "session", "sessionID": self.sid})
        self.emit({"type": "hi.loaded", "skills": sorted(s["name"] for s in self.call("GET", "/skill")),
                   "mcp": self.call("GET", "/mcp")})
        events = self.http.open(urllib.request.Request(self.base + "/event" + self.query, headers=self.auth))
        self.pump(sse(events), "sse")
        if self.stopping:
            self.finish("stopped")

    # --- the contract's methods -----------------------------------------------------------------
    def on_line(self, source, line):
        if source == "server":
            m = re.search(r"listening on (http://\S+)", line)
            self.emit({"type": "hi.text", "source": "opencode", "text": line})
            if m and not self.base:
                self.base = m.group(1)
                self.ready()
            return
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
        elif p.get("sessionID") != self.sid:
            return
        elif kind == "session.error":
            err = p.get("error") or {}
            self.emit({"type": "error", "sessionID": self.sid, "error": err})
            if err.get("name") == "MessageAbortedError":
                self.aborted = True
            else:
                self.error = err
        elif kind == "session.status":
            status = p.get("status") or {}
            if status.get("type") == "busy":
                self.busy = True
            elif status.get("type") == "retry":
                self.emit({"type": "retry", "sessionID": self.sid, "status": status})
            elif status.get("type") == "idle" and self.busy:
                self.on_idle()
        elif kind == "permission.asked":                         # the config allows all; never hang
            self.call("POST", f"/permission/{p['id']}/reply", {"reply": "once"})
        elif kind == "question.asked":
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
            for key, path in TOKENS.items():
                self.usage[key] += dig(part.get("tokens") or {}, path) or 0
            self.cost += part.get("cost") or 0.0
            self.out.write(**self.fields())

    def fields(self) -> dict:
        answer = next(("\n".join(self.texts[m]) for m in reversed(self.assistants) if self.texts.get(m)), "")
        unpriced = not self.cost and self.usage["output_tokens"]          # a model outside its catalog: 0
        return {"answer": answer, "usage": self.usage, "cost_usd": None if unpriced else round(self.cost, 6)}

    def on_idle(self) -> None:
        fields = self.fields()
        if self.stopping or self.aborted:
            return self.finish("stopped", **fields)
        if self.error:
            message = (self.error.get("data") or {}).get("message", "")
            return self.finish("fail", **{**fields, "answer": fields["answer"] or f"{self.error.get('name')}: {message}"})
        answered = len(self.users) >= self.sent and self.assistants and self.users[-1] < self.assistants[-1]
        if answered:
            self.finish("ok", **fields)
        # else a prompt is still on its way into OpenCode's loop: the next busy -> idle finishes

    def steer(self, text):
        if self.prompted:
            self.prompt(text)
        else:
            self.pending.append(text)

    def stop(self):
        if not self.prompted:                                     # nothing running yet
            return self.finish("stopped")
        self.call("POST", f"/session/{self.sid}/abort", {})

    def on_finish(self):
        try:
            os.killpg(self.server.pid, signal.SIGTERM)            # it closes its database; _reap kills after
        except (AttributeError, ProcessLookupError, PermissionError):
            pass


if __name__ == "__main__":
    OpenCodeAdapter().main()
