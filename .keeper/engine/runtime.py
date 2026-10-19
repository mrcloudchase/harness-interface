"""harness-interface, as Keeper uses it: every agent turn is one response from a running server, in
a sandbox that reaches only its provider. Providers and harnesses are registered with `hi`; turns
and their files go through the HTTP API. Nothing else in the engine runs an agent."""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from env import clean

INTERNAL = (".home/", ".hi/")               # a harness's own state; never part of the project


class HarnessError(RuntimeError):
    """harness-interface refused a request or could not be reached."""


class Runtime:
    def __init__(self, root: Path, url: str = "http://127.0.0.1:8000", sandboxed: bool = True):
        """`sandboxed`: every turn must have run in a Docker sandbox. In GitHub Actions a turn on the
        local runtime would inherit the runner's environment, credentials included."""
        self.root, self.url, self.sandboxed = Path(root), url.rstrip("/"), sandboxed
        self._ready: dict[str, set[str]] = {}    # harness → the files it writes for itself

    # ── setup ──────────────────────────────────────────────────────────────────────────────────
    def _hi(self, *args: str, env: dict[str, str] | None = None) -> str:
        r = subprocess.run(["hi", "--url", self.url, *args], capture_output=True, text=True, env=clean(env))
        if r.returncode != 0:
            raise HarnessError(f"hi {' '.join(args[:2])}: {r.stderr.strip() or r.stdout.strip()}")
        return r.stdout

    def provider(self, name: str, url: str, key: str) -> None:
        """Register a provider; the key travels in the environment, never on a command line."""
        self._hi("provider", "add", name, "--url", url, "--key-env", "KEEPER_PROVIDER_KEY",
                 env={"KEEPER_PROVIDER_KEY": key})

    def harness(self, name: str) -> set[str]:
        """Register a harness: the project's own folder of that name if it has one, else the shipped
        one. Returns the files it writes into the workspace for itself, which are never the agent's work."""
        if name not in self._ready:
            folder = self.root / "harnesses" / name
            self._hi("harness", "add", *([str(folder)] if (folder / "harness.json").is_file() else ["--builtin", name]))
            spec = json.loads(self._hi("harness", "show", name))
            self._ready[name] = set(spec.get("files", {}))
        return self._ready[name]

    # ── turns ──────────────────────────────────────────────────────────────────────────────────
    def _call(self, method: str, path: str, body: dict | None = None, raw: bool = False):
        req = urllib.request.Request(f"{self.url}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3600) as r:
                data = r.read()
        except urllib.error.HTTPError as e:
            raise HarnessError(f"{method} {path}: {e.code} {e.read().decode(errors='replace')[:300]}") from None
        except urllib.error.URLError as e:
            raise HarnessError(f"no harness-interface at {self.url}: {e.reason}") from None
        return data if raw else json.loads(data)

    def turn(self, harness: str, instructions: str, text: str, files: dict[str, str] | None = None,
             previous: str | None = None) -> dict:
        """One turn, to the end. Returns the record: status, answer, cost, files changed."""
        self.harness(harness)
        items = [{"type": "input_text", "text": text},
                 *({"type": "input_file", "filename": k, "file_data": v} for k, v in (files or {}).items())]
        body = {"model": harness, "input": items, "instructions": instructions}
        if previous:
            body["previous_response_id"] = previous
        record = self._call("POST", "/responses", body)
        if self.sandboxed and record["harness"]["runtime"] != "docker":
            raise HarnessError(f"refusing a turn on the {record['harness']['runtime']} runtime: agents run sandboxed")
        return record

    def changes(self, record: dict) -> dict[str, bytes | None]:
        """What a turn changed in the project: each changed file's new bytes, None for a deletion.
        The harness's own files and state are left out."""
        h, own = record["harness"], self._ready.get(record["harness"]["name"], set())
        keep = lambda p: p not in own and not p.startswith(INTERNAL) and p != "keeper.json"
        out: dict[str, bytes | None] = {p: self.file(record["id"], p) for p in h.get("files", []) if keep(p)}
        out.update({p: None for p in h.get("deleted", []) if keep(p)})
        return out

    def file(self, rid: str, path: str) -> bytes:
        return self._call("GET", f"/responses/{rid}/files/{path}", raw=True)

    def result(self, record: dict) -> dict:
        """What the agent wrote to keeper.json, the one channel for a structured answer; {} if none."""
        try:
            data = json.loads(self.file(record["id"], "keeper.json"))
        except (HarnessError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


def answer(record: dict) -> str:
    return "".join(c.get("text", "") for m in record.get("output", []) for c in m.get("content", []))


def cost(record: dict) -> float:
    return float(record["harness"].get("cost_usd") or 0.0)
