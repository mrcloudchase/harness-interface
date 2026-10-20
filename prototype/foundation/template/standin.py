#!/usr/bin/env python3
"""standin: a fake coding-agent CLI with no model, so the template runs end to end.

It behaves like the real ones in the ways the contract cares about:
- an RPC mode on stdin/stdout (one JSON command per line in, NDJSON events out), like pi --mode rpc;
- a session id announced first, and the session saved under $HOME after every step, so a kill
  loses nothing and `--resume ID` carries on;
- a "turn" counts to N (from "count to N" in the prompt) with a sleep per number, appending each
  number to count.txt in the workspace;
- steers land between steps ("count to K" in a steer moves the target); `abort` stops gracefully;
- optionally one real call to its provider (GET /v1/models) to prove the key and the egress path;
- an npm-installed helper (`semver`, from the tools dir) to prove the cached install is usable.

Commands: {"type":"prompt","text":…} {"type":"steer","text":…} {"type":"abort"}; EOF exits.
Events: session, tools, provider, steer_accepted, count, turn_end.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

lock = threading.Lock()


def emit(obj):
    with lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def target_of(text, default=None):
    m = re.search(r"count to (\d+)", text, re.I)
    return int(m.group(1)) if m else default


class Session:
    def __init__(self, directory, sid, resume):
        self.path = os.path.join(directory, f"{sid}.json")
        os.makedirs(directory, exist_ok=True)
        self.state = {"id": sid, "count": 0, "target": 0, "history": []}
        if resume:
            with open(self.path) as f:
                self.state = json.load(f)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.path)


def provider_check():
    base = os.environ.get("STANDIN_BASE_URL")
    if not base:
        return None
    key_file = os.environ.get("STANDIN_API_KEY_FILE")
    key = open(key_file).read().strip() if key_file else os.environ.get("STANDIN_API_KEY", "")
    if os.environ.get("STANDIN_API", "anthropic-messages") == "anthropic-messages":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        headers = {"authorization": f"Bearer {key}"}
    req = urllib.request.Request(base.rstrip("/") + "/v1/models", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"status": r.status}
    except urllib.error.HTTPError as e:
        return {"status": e.code}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:200]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume")
    ap.add_argument("--model", default="standin-1")
    ap.add_argument("--delay", type=float, default=float(os.environ.get("STANDIN_DELAY", "0.3")))
    a = ap.parse_args()
    sid = a.resume or str(uuid.uuid4())
    session = Session(os.path.join(os.environ["HOME"], ".standin", "sessions"), sid, bool(a.resume))
    session.save()
    emit({"type": "session", "id": sid, "resumed": bool(a.resume), "count": session.state["count"], "model": a.model})
    semver = subprocess.run(["semver", "1.2.3", "-i", "minor"], capture_output=True, text=True)
    emit({"type": "tools", "semver": semver.stdout.strip() or semver.stderr.strip()[:200]})

    inbox, abort = [], threading.Event()
    wake = threading.Condition()

    def read():
        for line in sys.stdin:
            cmd = json.loads(line)
            with wake:
                if cmd["type"] == "abort":
                    abort.set()
                else:
                    inbox.append(cmd)
                wake.notify()
        with wake:
            inbox.append({"type": "eof"})
            wake.notify()
    threading.Thread(target=read, daemon=True).start()

    while True:
        with wake:
            while not inbox:
                wake.wait()
            cmd = inbox.pop(0)
        if cmd["type"] == "eof":
            return
        if cmd["type"] == "steer":                      # idle: a steer is a new prompt
            cmd = {"type": "prompt", "text": cmd["text"]}
            emit({"type": "steer_accepted", "text": cmd["text"], "as_prompt": True})
        st = session.state
        st["history"].append({"role": "user", "text": cmd["text"]})
        st["target"] = target_of(cmd["text"], st["target"] or 5)
        abort.clear()
        if (p := provider_check()) is not None:
            emit({"type": "provider", **p})
        reason = "done"
        while st["count"] < st["target"]:
            time.sleep(a.delay)
            with wake:
                steers = [c for c in inbox if c["type"] == "steer"]
                inbox[:] = [c for c in inbox if c["type"] != "steer"]
            for s in steers:
                st["history"].append({"role": "user", "text": s["text"], "steer": True})
                st["target"] = target_of(s["text"], st["target"])
                emit({"type": "steer_accepted", "text": s["text"], "target": st["target"]})
            if abort.is_set():
                reason = "aborted"
                break
            st["count"] += 1
            session.save()
            with open("count.txt", "a") as f:               # the "work": a file in the workspace
                f.write(f"{st['count']}\n")
            emit({"type": "count", "n": st["count"]})
        text = f"Counted to {st['count']}." if reason == "done" else f"Stopped at {st['count']} of {st['target']}."
        st["history"].append({"role": "assistant", "text": text})
        session.save()
        emit({"type": "turn_end", "reason": reason, "count": st["count"], "text": text,
              "usage": {"input_tokens": len(cmd["text"].split()), "output_tokens": st["count"]}})


if __name__ == "__main__":
    main()
