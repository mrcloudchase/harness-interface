"""Prove a harness works end to end against a running platform, with any client's eyes: the OpenAI
SDK for the requests, plain HTTP for the session routes.

    python scripts/live.py --url http://127.0.0.1:8000 --key hi_… --harness claude-code[/provider/model]

It makes a file in a stateful session, continues the session and checks the harness remembers,
streams a turn, steers a long turn (the steer lands after the turn ends), cancels one, reads the
trace and downloads the archive. The prompts are plain English, so any coding harness should pass;
each check prints PASS or FAIL with what came back. Exit status 1 if any failed.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import time

import httpx
from openai import OpenAI

MAKE = "Create a file named hello.txt in the current directory containing exactly the word hello. Then reply with the one word: done"
RECALL = "What file did you create in the previous turn? Reply with just its name."
COUNT = ("Run exactly this shell command with your shell tool, wait for it to finish, then reply with the one word: counted\n\n"
         "for i in $(seq 1 45); do echo $i >> count.txt; sleep 2; done")
STEER = "Stop counting. Whether or not it finished, reply now with just the one word: stopped"


def words(text: str) -> str:
    """The text with JSON-lines output flattened to its text strings, so a harness that streams
    token-sized pieces ({"text": "hel"} then {"text": "lo"}) still reads as hello."""
    keys = {"text", "data", "content", "contentDelta", "delta", "output"}

    def strings(v: object) -> list[str]:
        if isinstance(v, dict):
            return [s for k, x in v.items() for s in ([x] if k in keys and isinstance(x, str) else strings(x))]
        return [s for x in v for s in strings(x)] if isinstance(v, list) else []
    out = []
    for line in text.splitlines():
        try:
            out.append("".join(strings(json.loads(line))) if line.startswith("{") else line + "\n")
        except ValueError:
            out.append(line + "\n")
    return "".join(out)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--harness", required=True, help="a harness name, or harness/provider/model")
    a = p.parse_args()
    http = httpx.Client(base_url=a.url, headers={"Authorization": f"Bearer {a.key}"}, timeout=900)
    sdk = OpenAI(api_key=a.key, base_url=f"{a.url}/v1", timeout=900)
    failed = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal failed
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail[:300]!r}", flush=True)

    def detail(rid: str) -> dict:
        return http.get(f"/v1/responses/{rid}?detail=true").json()

    r1 = sdk.responses.create(model=a.harness, input=MAKE)
    sid = r1.metadata["session_id"]
    check("make", r1.status == "completed" and "done" in words(r1.output_text).lower(), r1.output_text)
    r2 = sdk.responses.create(model=a.harness, input=RECALL, previous_response_id=r1.id)
    check("recall", r2.status == "completed" and "hello.txt" in words(r2.output_text), r2.output_text)
    archive = http.get(f"/v1/sessions/{sid}/archive")
    with tarfile.open(fileobj=io.BytesIO(archive.content)) as tar:
        names = tar.getnames()
        hello = tar.extractfile("./hello.txt").read().decode().strip() if "./hello.txt" in names else ""
    check("archive", hello == "hello", f"{hello!r} in {names[:8]}")
    deltas = [e.delta for e in sdk.responses.create(model=a.harness, input="Reply with the one word: streamed",
                                                    previous_response_id=r2.id, stream=True)
              if e.type == "response.output_text.delta"]
    check("stream", "streamed" in words("".join(deltas)).lower() and len(deltas) > 1, "".join(deltas))

    def running_for(rid: str, seconds: float) -> bool:
        started = time.time()
        while time.time() - started < 90:
            if http.get(f"/v1/responses/{rid}").json()["status"] != "in_progress":
                return False
            if time.time() - started >= seconds and detail(rid)["stdout"]:
                return True
            time.sleep(1)
        return True

    r3 = sdk.responses.create(model=a.harness, input=COUNT, previous_response_id=r2.id, background=True)
    if not running_for(r3.id, 8):
        print("NOTE the counting turn ended before a steer could land (the harness finished or refused it)")
    steer = http.post(f"/v1/sessions/{sid}/interrupt", json={"input": STEER})
    check("interrupt accepted", steer.status_code == 200, steer.text)
    for _ in range(150):
        got = http.get(f"/v1/responses/{r3.id}").json()
        if got["status"] != "in_progress":
            break
        time.sleep(2)
    text = got["output"][0]["content"][0]["text"]
    check("steer", got["status"] == "completed" and "stopped" in words(text).lower(), text[-300:])

    r4 = sdk.responses.create(model=a.harness, input=COUNT, previous_response_id=r3.id, background=True)
    if not running_for(r4.id, 6):
        print("NOTE the counting turn ended before a cancel could land")
    cancelled = http.post(f"/v1/responses/{r4.id}/cancel").json()
    check("cancel", cancelled["status"] == "cancelled", cancelled["status"])
    trace = http.get(f"/v1/sessions/{sid}/trace").json()["data"]
    kinds = [t["kind"] for t in trace]
    check("trace", kinds.count("request") == 5 and "interrupt" in kinds and "cancel" in kinds, " ".join(kinds))
    stateless = sdk.responses.create(model=a.harness, input="Reply with the one word: stateless", store=False)
    kept = http.get(f"/v1/sessions/{stateless.metadata['session_id']}").json()
    check("stateless", stateless.status == "completed" and kept["stored"] is False, f"{stateless.output_text[:80]!r} stored={kept['stored']}")
    print("ALL PASSED" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
