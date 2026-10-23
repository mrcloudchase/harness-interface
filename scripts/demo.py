"""Watch one harness take a streamed turn and a steer, from a terminal.

    python scripts/demo.py --url http://127.0.0.1:8000 --key hi_… --harness claude-code

It streams a turn that runs a slow shell loop, relays the package's live stdout as text, sends a
steer while the turn is running, and prints what the package returned. The key is read from
`--key` or `HI_KEY` and never printed, so the run can be recorded as it is.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time

import httpx

COUNT = ("Run exactly this shell command with your shell tool, wait for it to finish, then reply with the one word: counted\n\n"
         "for i in $(seq 1 12); do echo tick $i; sleep 1; done")
STEER = "Stop counting. Whether or not it finished, reply now with just the one word: stopped"
KEYS = {"text", "data", "content", "contentDelta", "delta", "output"}
DIM, BOLD, GREEN, YELLOW, RESET = "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[0m"


def strings(v: object) -> list[str]:
    """The human-readable strings in a JSON event: text fields, and shell commands as `$ cmd`."""
    if isinstance(v, dict):
        out = []
        for k, x in v.items():
            if k in KEYS and isinstance(x, str):
                out.append(x)
            elif k == "command" and isinstance(x, str):
                out.append(f"$ {x}")
            else:
                out += strings(x)
        return out
    return [s for x in v for s in strings(x)] if isinstance(v, list) else []


def flatten(text: str) -> str:
    """JSON lines become their strings, one per line; other lines pass through; empty ones are dropped."""
    out = []
    for ln in text.splitlines():
        try:
            words = " ".join(strings(json.loads(ln))) if ln.startswith("{") else ln
        except ValueError:
            words = ln
        if words.strip():
            out.append(words.rstrip())
    return "".join(f"{ln}\n" for ln in out)


def say(label: str, text: str = "", color: str = BOLD) -> None:
    print(f"\n{color}{label}{RESET} {text}".rstrip(), flush=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get("HI_URL", "http://127.0.0.1:8000"))
    p.add_argument("--key", default=os.environ.get("HI_KEY", ""))
    p.add_argument("--harness", required=True)
    p.add_argument("--steer-after", type=float, default=8, help="seconds of live output before the steer is sent")
    a = p.parse_args()
    if not a.key:
        print("give --key or HI_KEY", file=sys.stderr)
        return 2
    http = httpx.Client(base_url=a.url, headers={"Authorization": f"Bearer {a.key}"}, timeout=900)

    say("harness", a.harness)
    say("request", f"POST /v1/responses  model={a.harness}  stream=true")
    print(f"{DIM}{COUNT}{RESET}")
    say("live stdout", "(request.sh, relayed as it is written)", DIM)
    started = time.time()
    first_output: list[float] = []
    sid: list[str] = []
    rid: list[str] = []
    final: list[dict] = []
    steered = threading.Event()

    def steer() -> None:
        while not first_output and not final:
            time.sleep(0.2)
        while not final and time.time() - (first_output[0] if first_output else started) < a.steer_after:
            time.sleep(0.2)
        if final or not sid:
            return
        r = http.post(f"/v1/sessions/{sid[0]}/interrupt", json={"input": STEER})
        say("steer", f"POST /v1/sessions/{{id}}/interrupt -> {r.status_code}", YELLOW)
        print(f"{DIM}{STEER}{RESET}", flush=True)
        steered.set()

    threading.Thread(target=steer, daemon=True).start()
    body = {"model": a.harness, "input": COUNT, "stream": True}
    with http.stream("POST", "/v1/responses", json=body) as r:
        if r.status_code != 200:
            say("refused", r.read().decode(), YELLOW)
            return 1
        sid.append(r.headers.get("x-session-id", ""))
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                event, buf = buf.split("\n\n", 1)
                line = next((ln for ln in event.split("\n") if ln.startswith("data: ")), "")
                if not line:
                    continue
                d = json.loads(line[6:])
                if d["type"] == "response.created":
                    rid.append(d["response"]["id"])
                elif d["type"] == "response.output_text.delta":
                    if not first_output:
                        first_output.append(time.time())
                    sys.stdout.write(flatten(d["delta"]))
                    sys.stdout.flush()
                elif d["type"].startswith("response.") and d.get("response") and d["type"] not in ("response.created", "response.in_progress"):
                    final.append(d["response"])
    f = final[-1] if final else {}
    say("response", f"status={f.get('status')}  exit_code={f.get('metadata', {}).get('exit_code')}  {round(time.time() - started)}s", GREEN)
    text = flatten(f.get("output", [{}])[0].get("content", [{}])[0].get("text", "")).splitlines()
    print("\n".join(text[-6:]) if len(text) > 6 else "\n".join(text))
    if len(text) > 6:
        print(f"{DIM}(the last 6 of {len(text)} lines; the package returns request.sh's stdout as it is){RESET}")
    say("trace", "GET /v1/sessions/{id}/trace", DIM)
    for t in http.get(f"/v1/sessions/{sid[0]}/trace").json()["data"]:
        print(f"  {t['kind']:<9} {t['response'][:20]}…  {json.dumps(t['body'].get('input', ''))[:70] if t['kind'] in ('request', 'interrupt') else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
