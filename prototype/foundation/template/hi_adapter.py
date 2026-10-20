"""hi_adapter: the plumbing every adapter shares (contract v1).

Copied byte-identical into every harness folder; `hirun.py check` and the foundation tests fail
when a copy drifts. A folder stays self-contained (it runs with only itself, its tools dir and the
base image) and the contract stays env + stdin + files: the runner never injects code.

What it does, so an adapter only says how its CLI starts, steers, stops and reports:
- reads line 1 of stdin (the request; pretty-printed JSON is tolerated);
- turns every later stdin line (one JSON string) into a steer, and EOF into a graceful stop;
- turns SIGINT/SIGTERM into a graceful stop; a stop not finished in `stop_grace_s` kills the CLI;
- writes $HI_OUTPUT atomically (tmp + rename), early and at the end;
- starts the CLI and its daemons in their own session, and kills their groups on the way out.

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
FIELDS = ("answer", "status", "resume", "usage", "cost_usd", "steers")


class Output:
    """$HI_OUTPUT: {answer, status, resume, usage, cost_usd, steers}, every write complete."""

    def __init__(self, path: str | None = None):
        self.path = path or os.environ["HI_OUTPUT"]
        self.data = {"answer": "", "status": "running", "resume": None, "usage": {}, "cost_usd": None, "steers": 0}

    def write(self, **fields) -> None:
        unknown = set(fields) - set(FIELDS)
        assert not unknown, f"not an output field: {sorted(unknown)}"
        assert fields.get("status", "running") in STATUSES, f"bad status {fields['status']!r}"
        self.data.update(fields)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


def read_request(stream=sys.stdin) -> dict:
    """Line 1: {task, instructions, model, resume, metadata}. Lines are joined until they parse."""
    buf = ""
    for line in stream:
        buf += line
        try:
            req = json.loads(buf)
            break
        except json.JSONDecodeError:
            continue
    else:
        raise SystemExit("hi_adapter: stdin ended before a request")
    assert isinstance(req, dict) and isinstance(req.get("task"), str), "request must be an object with a task"
    return {"instructions": "", "model": os.environ.get("HI_MODEL", ""), "resume": os.environ.get("HI_RESUME") or None,
            "metadata": {}, **req}


def provider_key() -> str:
    """The provider key, read from $HI_PROVIDER_KEY_FILE. Pass the file path on to a CLI that can
    read one; call this only for a CLI that needs the value itself."""
    with open(os.environ["HI_PROVIDER_KEY_FILE"]) as f:
        return f.read().strip()


def child_env(**extra: str) -> dict:
    """The adapter's environment for a CLI, with loopback never proxied."""
    env = {**os.environ, **extra}
    env["NO_PROXY"] = env["no_proxy"] = ",".join(sorted({"127.0.0.1", "localhost", *env.get("NO_PROXY", "").split(",")} - {""}))
    return env


class Adapter:
    """One event loop over a queue fed by the CLI's output, stdin and signals. Subclass and define
    start(request), on_line(source, line), steer(text) and stop(); call finish(status, ...) when done."""

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
    def on_exit(self, source: str, code: int) -> None:
        """A spawned process ended. Default: if the run is not finished, it failed (or was stopped)."""
        if not self.finished:
            self.finish("stopped" if self.stopping_since else "fail", answer=self.out.data["answer"] or f"{source} exited {code}")

    # --- tools ---------------------------------------------------------------------------------
    def spawn(self, argv: list[str], name: str = "cli", stdin=subprocess.PIPE, env: dict | None = None,
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
        if self.stopping_since is None and not self.finished:
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
        if request.get("resume"):
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
                    if self.stopping_since is None:
                        self.steer(value)
                elif source and source.endswith(":exit"):
                    self.on_exit(source[:-5], value)
                elif source:
                    self.on_line(source, value)
                if self.stopping_since and time.monotonic() - self.stopping_since > self.stop_grace_s:
                    self.finish("stopped", answer=self.out.data["answer"] or "stopped (killed after grace)")
        except Exception as e:  # noqa: BLE001 - an adapter bug is a failed run, never a hang
            self.finish("fail", answer=f"adapter error: {type(e).__name__}: {e}")
            raise
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
