"""The live check of every shipped harness: two turns each, through a real server and real
providers, in Docker sandboxes. It passes when every harness whose provider has a key answers
both turns, follows the instructions, and remembers the first turn in the second.

    python scripts/live_matrix.py                  every harness with a key
    python scripts/live_matrix.py codex pi         just these

Keys come from ANTHROPIC_API_KEY, OPENAI_API_KEY and DEEPSEEK_API_KEY. The server runs from this
checkout, on HI_RUNTIME (docker unless set), and never sees a key in its environment.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {"anthropic": ("https://api.anthropic.com", "ANTHROPIC_API_KEY"),
             "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
             "deepseek": ("https://api.deepseek.com/anthropic", "DEEPSEEK_API_KEY"),
             "deepseek-openai": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY")}
INSTRUCTIONS = "End every answer with the word PELICAN."
FIRST, SECOND = "Remember the word ORCHID. Reply OK.", "Which word did I ask you to remember?"


def call(url: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(f"{url}{path}", method=method, headers={"Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.loads(r.read())


def answer(record: dict) -> str:
    return "".join(c.get("text", "") for m in record.get("output", []) for c in m.get("content", []))


def check(url: str, harness: str) -> tuple[str, bool, str]:
    try:
        one = call(url, "POST", "/responses", {"model": harness, "input": FIRST, "instructions": INSTRUCTIONS})
        two = call(url, "POST", "/responses", {"model": harness, "input": SECOND, "instructions": INSTRUCTIONS,
                                               "previous_response_id": one["id"]})
    except Exception as e:  # noqa: BLE001 — any failure is this harness's result, and the run goes on
        return harness, False, f"{type(e).__name__}: {e}"
    a, b = answer(one), answer(two)
    problems = [p for p, bad in (
        (f"turn 1 {one['status']}", one["status"] != "completed"), (f"turn 2 {two['status']}", two["status"] != "completed"),
        ("turn 1 ignored the instructions", "PELICAN" not in a.upper()),
        ("turn 2 ignored the instructions", "PELICAN" not in b.upper()),
        ("turn 2 forgot turn 1", "ORCHID" not in b.upper())) if bad]
    return harness, not problems, "; ".join(problems) or f"{one['id']} → {two['id']}"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main(only: list[str]) -> int:
    keys = {name: os.environ.get(var, "") for name, (_, var) in PROVIDERS.items()}
    port, data = free_port(), Path(tempfile.mkdtemp(prefix="live-matrix-"))
    url = f"http://127.0.0.1:{port}"
    env = {k: v for k, v in os.environ.items() if not k.endswith(("_KEY", "_TOKEN", "_SECRET")) and k != "KEEPER_SECRETS"}
    env.update(HI_PORT=str(port), HI_DATA_DIR=str(data), HI_RUNTIME=os.environ.get("HI_RUNTIME", "docker"))
    server = subprocess.Popen([sys.executable, "-c", "from harness_interface.api.app import main; main()"],
                              env=env, stdout=open(data / "server.log", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                call(url, "GET", "/sandboxes")
                break
            except OSError:
                time.sleep(0.5)
        for name, (provider_url, _) in PROVIDERS.items():
            if keys[name]:
                call(url, "PUT", f"/providers/{name}", {"name": name, "url": provider_url, "key": keys[name]})
        folders = sorted(p for p in (ROOT / "harnesses").iterdir() if (p / "harness.json").is_file())
        run, skipped = [], []
        for folder in folders:
            spec = json.loads((folder / "harness.json").read_text())
            if only and spec["name"] not in only:
                continue
            if not keys.get(spec["provider"]):
                skipped.append(spec["name"])
                continue
            spec["scripts"] = {p.name: p.read_text() for p in folder.iterdir() if p.is_file() and p.name != "harness.json"}
            call(url, "PUT", f"/harnesses/{spec['name']}", spec)
            run.append(spec["name"])
        if not run:
            print("no harness has a provider key: set ANTHROPIC_API_KEY, OPENAI_API_KEY or DEEPSEEK_API_KEY")
            return 1
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(lambda h: check(url, h), run))
    finally:
        server.terminate()
        server.wait(30)
    for harness, ok, detail in results:
        print(f"{'pass' if ok else 'FAIL'}  {harness:<22} {detail}")
    for harness in skipped:
        print(f"skip  {harness:<22} no key for its provider")
    failed = [h for h, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} harnesses pass" + (f"; {len(skipped)} skipped" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
