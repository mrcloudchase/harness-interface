"""hi_adapter: the plumbing every adapter shares (contract 1).

Copied byte-identical into every harness folder; the server refuses a folder whose copy differs from
the one it ships. A folder stays self-contained (it runs with only itself, its tools directory and the
base image) and the contract stays environment, stdin and files: the server never injects code.

What it does, so an adapter only says how its CLI starts, steers, stops and reports:
- reads line 1 of stdin, `{"task", "resume"}`, and adds the model from $HI_MODEL;
- turns every later stdin line (one JSON string) into a steer, and the end of stdin into a stop;
- turns SIGINT and SIGTERM into a graceful stop; a stop not finished in `stop_grace_s` finishes
  `stopped` and the CLI is killed;
- writes $HI_OUTPUT atomically (tmp, fsync, rename), early and at the end, with any keys it is given;
- starts the CLI and its daemons in their own sessions, and kills their groups on the way out;
- speaks JSON-RPC 2.0 over a CLI's stdio for app-server and ACP style CLIs (`JsonRpc`).

Stdlib only. Python >= 3.9.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

STATUSES = ("running", "ok", "fail", "stopped")
USAGE = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")


class Output:
    """$HI_OUTPUT: `answer`, `status`, `resume`, `usage` (the USAGE keys, others allowed), `cost_usd`,
    `steers`, and any other key the adapter wants to report. Every write is complete."""

    def __init__(self, path: str | None = None):
        self.path = path or os.environ["HI_OUTPUT"]
        self.data = {"answer": "", "status": "running", "resume": None, "usage": {}, "cost_usd": None, "steers": 0}

    def write(self, **fields) -> None:
        assert fields.get("status", "running") in STATUSES, f"bad status {fields['status']!r}"
        self.data.update(fields)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


def read_request(stream=sys.stdin) -> dict:
    """Line 1: {"task", "resume"}, with "model" from $HI_MODEL ("" when none)."""
    line = stream.readline()
    if not line:
        raise SystemExit("hi_adapter: stdin ended before a request")
    req = json.loads(line)
    assert isinstance(req, dict) and isinstance(req.get("task"), str), "line 1 must be an object with a task"
    return {"resume": None, **req, "model": os.environ.get("HI_MODEL", "")}


def provider_key() -> str:
    """The credential, read from $HI_PROVIDER_KEY_FILE. Pass the file's path on to a CLI that can read
    one; call this only for a CLI that needs the value itself."""
    with open(os.environ["HI_PROVIDER_KEY_FILE"]) as f:
        return f.read().strip()


def child_env(**extra: str) -> dict:
    """The adapter's environment for a CLI, with loopback never proxied."""
    env = {**os.environ, **extra}
    hosts = {"127.0.0.1", "localhost", *env.get("NO_PROXY", "").split(",")} - {""}
    env["NO_PROXY"] = env["no_proxy"] = ",".join(sorted(hosts))
    return env


class JsonRpc:
    """JSON-RPC 2.0 over a process's stdin, one message per line. `call` sends a request and runs
    then(result, error) when its reply arrives; `dispatch` takes every message the process printed,
    runs the callback of a reply, answers a request from the process with answer(method, params), and
    says whether the adapter has anything left to do with the message (a notification)."""

    def __init__(self, proc: subprocess.Popen, answer=None):
        self.proc, self.answer = proc, answer or (lambda method, params: {})
        self.next_id, self.waiting = 0, {}

    def send(self, message: dict) -> None:
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params=None) -> None:
        self.send({"method": method, **({"params": params} if params is not None else {})})

    def call(self, method: str, params, then=None) -> int:
        self.next_id += 1
        self.waiting[self.next_id] = then or (lambda result, error: None)
        self.send({"id": self.next_id, "method": method, "params": params})
        return self.next_id

    def dispatch(self, message: dict) -> bool:
        """True if `message` was a notification, for the adapter to handle."""
        if "method" in message and "id" in message:
            self.send({"id": message["id"], "result": self.answer(message["method"], message.get("params"))})
            return False
        if "id" in message:
            then = self.waiting.pop(message["id"], None)
            if then:
                then(message.get("result"), message.get("error"))
            return False
        return True


class Adapter:
    """One event loop over a queue fed by the CLI's output, stdin and signals. Subclass and define
    start(request), on_line(source, line), steer(text) and stop(); call finish(status, ...) when done.
    on_finish() runs once before the CLIs are reaped, to close them cleanly."""

    stop_grace_s = 10.0

    def __init__(self):
        self.out = Output()
        self.events: queue.Queue = queue.Queue()
        self.children: list[subprocess.Popen] = []
        self.stopping_since: float | None = None
        self.finished = False

    # --- to define -----------------------------------------------------------------------------
    def start(self, request: dict) -> None: raise NotImplementedError
    def on_line(self, source: str, line: str) -> None: raise NotImplementedError
    def steer(self, text: str) -> None: raise NotImplementedError
    def stop(self) -> None: raise NotImplementedError
    def on_finish(self) -> None: pass

    def on_exit(self, source: str, code: int) -> None:
        """A spawned process ended. Default: if the run is not finished, it failed (or was stopped)."""
        if not self.finished:
            answer = self.out.data["answer"] or f"{source} exited {code}"
            self.finish("stopped" if self.stopping else "fail", answer=answer)

    # --- tools ---------------------------------------------------------------------------------
    @property
    def stopping(self) -> bool:
        """Whether a stop was asked for: an ending now is `stopped`, not a failure."""
        return self.stopping_since is not None

    def spawn(self, argv: list, name: str = "cli", stdin=subprocess.PIPE, env: dict | None = None,
              stderr=None) -> subprocess.Popen:
        """Start a process in its own session (our SIGINT never reaches it), cwd = the workspace.
        Each stdout line arrives as on_line(name, line); its exit as on_exit(name, code)."""
        proc = subprocess.Popen(argv, cwd=os.environ.get("HI_WORKSPACE"), env=env or child_env(), stdin=stdin,
                                stdout=subprocess.PIPE, stderr=stderr, text=True, bufsize=1, start_new_session=True)
        self.children.append(proc)

        def pump():
            for line in proc.stdout:
                self.events.put((name, line.rstrip("\n")))
            self.events.put((f"{name}:exit", proc.wait()))
        threading.Thread(target=pump, daemon=True).start()
        return proc

    def pump(self, lines, name: str) -> None:
        """Another source of events (an SSE stream, a socket): each item of `lines` arrives as
        on_line(name, item), read on a thread of its own."""
        def read():
            for line in lines:
                self.events.put((name, line))
        threading.Thread(target=read, daemon=True).start()

    @staticmethod
    def emit(obj) -> None:
        """One NDJSON event on stdout."""
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def accepted_steer(self) -> None:
        self.out.write(steers=self.out.data["steers"] + 1)

    def finish(self, status: str, **fields) -> None:
        self.out.write(status=status, **fields)
        self.finished = True

    # --- the loop ------------------------------------------------------------------------------
    def _request_stop(self, why: str) -> None:
        if not self.stopping and not self.finished:
            self.stopping_since = time.monotonic()
            self.emit({"type": "hi.stop", "why": why})
            self.stop()

    def _stdin(self) -> None:
        for line in sys.stdin:
            if line.strip():
                self.events.put(("hi.steer", json.loads(line)))
        self.events.put(("hi.eof", None))

    def main(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda s, _f: self.events.put(("hi.signal", signal.Signals(s).name)))
        request = read_request()
        if request["resume"]:
            self.out.write(resume=request["resume"])
        threading.Thread(target=self._stdin, daemon=True).start()
        try:
            self.start(request)
            while not self.finished:
                try:
                    source, value = self.events.get(timeout=0.2)
                except queue.Empty:
                    source, value = None, None
                if source in ("hi.signal", "hi.eof"):
                    self._request_stop(value or "eof")
                elif source == "hi.steer":
                    if not self.stopping:
                        self.steer(value)
                elif source and source.endswith(":exit"):
                    self.on_exit(source[:-5], value)
                elif source:
                    self.on_line(source, value)
                if self.stopping and time.monotonic() - self.stopping_since > self.stop_grace_s:
                    self.finish("stopped", answer=self.out.data["answer"] or "stopped (killed after grace)")
        except Exception as e:  # noqa: BLE001 - an adapter bug is a failed run, never a hang
            self.finish("fail", answer=f"adapter error: {type(e).__name__}: {e}")
            raise
        finally:
            try:
                self.on_finish()
            finally:
                self._reap()

    def _reap(self, wait_s: float = 3.0) -> None:
        """Close the CLIs' stdin, give them `wait_s` to exit, then kill their process groups."""
        for p in self.children:
            try:
                p.stdin and p.stdin.close()
            except OSError:
                pass
        deadline = time.monotonic() + wait_s
        for p in self.children:
            try:
                p.wait(max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
