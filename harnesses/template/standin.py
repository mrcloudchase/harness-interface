#!/usr/bin/env python3
"""standin: a fake coding-agent CLI with no model, so the template runs end to end.

It behaves like the real ones in the ways the contract cares about:
- an RPC mode on stdin/stdout (one JSON command per line in, NDJSON events out), like pi --mode rpc;
- a session id announced first, and the session saved under $HOME after every step, so a kill
  loses nothing and `--resume ID` carries on;
- config artifacts read from $HOME/.standin (instructions in AGENTS.md, config.json, skills/*/SKILL.md),
  announced in a `loaded` event;
- memory it writes itself, $HOME/.standin/memory/<id>.md, one line per prompt (a reported artifact);
- a "turn" counts to N (from "count to N" in the prompt) with a sleep per number, appending each
  number to count.txt in the workspace;
- steers land between steps ("count to K" in a steer moves the target); `abort` stops gracefully;
- with a provider, one call to it (GET <base>/v1/models or <base>/models) with the credential from its key file;
- an npm-installed helper (`semver`, from the tools directory) to prove the cached install is usable.

Commands: {"type":"prompt","text":…} {"type":"steer","text":…} {"type":"abort"}; the end of stdin exits.
Events: session, loaded, tools, provider, steer_accepted, count, turn_end.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

lock = threading.Lock()
HOME = os.path.join(os.environ["HOME"], ".standin")


def emit(obj):
    with lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def target_of(text, default=None):
    m = re.search(r"count to (\d+)", text, re.I)
    return int(m.group(1)) if m else default


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


class Session:
    def __init__(self, sid, resume):
        self.path = os.path.join(HOME, "sessions", f"{sid}.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.state = {"id": sid, "count": 0, "target": 0, "history": []}
        if resume:
            with open(self.path) as f:
                self.state = json.load(f)

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.path)

    def remember(self, text):
        os.makedirs(os.path.join(HOME, "memory"), exist_ok=True)
        with open(os.path.join(HOME, "memory", f"{self.state['id']}.md"), "a") as f:
            f.write(f"- {text}\n")


def provider_check():
    base = os.environ.get("STANDIN_BASE_URL")
    if not base:
        return None
    key = read(os.environ["STANDIN_API_KEY_FILE"]).strip()
    if os.environ.get("STANDIN_API") == "anthropic-messages":    # the SDK's base has no version path
        url, headers = base.rstrip("/") + "/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:                                                         # the OpenAI SDK's base ends with it
        url, headers = base.rstrip("/") + "/models", {"authorization": f"Bearer {key}"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
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
    session = Session(sid, bool(a.resume))
    session.save()
    emit({"type": "session", "id": sid, "resumed": bool(a.resume), "count": session.state["count"], "model": a.model})
    emit({"type": "loaded", "instructions": read(os.path.join(HOME, "AGENTS.md")),
          "config": json.loads(read(os.path.join(HOME, "config.json")) or "null"),
          "skills": sorted(os.path.basename(os.path.dirname(p)) for p in glob.glob(f"{HOME}/skills/*/SKILL.md"))})
    try:
        semver = subprocess.run(["semver", "1.2.3", "-i", "minor"], capture_output=True, text=True).stdout.strip()
    except OSError:
        semver = None
    emit({"type": "tools", "semver": semver})

    inbox, abort = [], threading.Event()
    wake = threading.Condition()

    def listen():
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
    threading.Thread(target=listen, daemon=True).start()

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
        session.remember(cmd["text"])
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
                session.remember(s["text"])
                emit({"type": "steer_accepted", "text": s["text"], "target": st["target"]})
            if abort.is_set():
                reason = "aborted"
                break
            st["count"] += 1
            session.save()
            with open("count.txt", "a") as f:               # the work: a file in the workspace
                f.write(f"{st['count']}\n")
            emit({"type": "count", "n": st["count"]})
        text = f"Counted to {st['count']}." if reason == "done" else f"Stopped at {st['count']} of {st['target']}."
        st["history"].append({"role": "assistant", "text": text})
        session.save()
        emit({"type": "turn_end", "reason": reason, "count": st["count"], "text": text,
              "usage": {"input_tokens": len(cmd["text"].split()), "output_tokens": st["count"]}})


if __name__ == "__main__":
    main()
