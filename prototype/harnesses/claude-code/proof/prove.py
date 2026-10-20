#!/usr/bin/env python3
"""Stage-2 proofs for the claude-code folder, through the foundation's hirun (imported, unmodified).
Not part of the harness contract; the runner never reads this directory.

    python3 prove.py local                 # one-shot, resume, steer, stop+continue, AGENTS.md (host)
    python3 prove.py docker gateway|file   # install miss/hit + the same four, sandboxed
    python3 prove.py deepseek              # docker + gateway against api.deepseek.com/anthropic
    python3 prove.py deepseek-file         # docker + file: one-shot, stop + continue on DeepSeek
    python3 prove.py extras                # loud egress (no NONESSENTIAL switch); lingering instructions
    python3 prove.py audit                 # key/token search over everything the runs left
Results: proof/results-<group>.json, one JSON per run in proof/runs/. Keys are never printed.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FOLDER = HERE.parent
FOUNDATION = FOLDER.parent.parent / "foundation"
sys.path.insert(0, str(FOUNDATION))
import hirun  # noqa: E402

SECRETS = Path("/home/user/harness-interface/data/secrets")
KEYS = {"anthropic": SECRETS / "ANTHROPIC_API_KEY", "deepseek": SECRETS / "DEEPSEEK_API_KEY"}
COUNT = ("Using the shell, write the numbers 1 to 30 to count.txt, one per line, running `sleep 1` between each "
         "number (one shell command per number). Do not write them all at once.")
STEER = "Stop counting now. Instead write the word DONE into done.txt and finish."
ASK = "What were you doing before you were stopped, and how far did you get? One sentence; do not continue the task."
RUNS = HERE / "runs"
results: dict = {}


def key_bytes(name):
    return KEYS[name].read_bytes().strip()


def proc_hits(secret: bytes, what: str, pids=None, ignore=frozenset()) -> list:
    hits = []
    for d in Path("/proc").glob("[0-9]*"):
        if d.name == str(os.getpid()) or (pids is not None and int(d.name) not in pids):
            continue
        try:
            data, comm = (d / what).read_bytes(), (d / "comm").read_text().strip()
        except OSError:
            continue
        if what == "environ":
            hits += [f"{comm}:{kv.split(b'=')[0].decode()}" for kv in data.split(b"\0")
                     if secret in kv and kv.split(b"=")[0].decode() not in ignore]
        elif secret in data:
            hits.append(comm)
    return sorted(set(hits))


def files_with(secret: bytes, root: Path) -> list:
    out = []
    for r, _, fs in os.walk(root):
        for n in fs:
            p = Path(r, n)
            try:
                if secret in p.read_bytes():
                    out.append(str(p.relative_to(root)))
            except OSError:
                pass
    return out


MACHINE_VARS = None


def machine_vars(secret: bytes) -> frozenset:
    """Variables that already hold the key on this machine (dockerd, shells: EXT_ANTHROPIC_API_KEY)."""
    return frozenset(h.split(":", 1)[1] for h in proc_hits(secret, "environ"))


class WatchRun(hirun.Run):
    """hirun.Run, plus: act when count.txt reaches `at` lines (steer or SIGINT), audit while running."""

    def __init__(self, folder, a, at=None, action=None, audit_key=None):
        super().__init__(folder, a)
        self.at, self.action, self.audit_key = at, action, audit_key
        self.fired = None
        self.audit = None

    def count(self):
        try:
            return len((self.ws / "count.txt").read_text().split())
        except OSError:
            return 0

    def on_stdout_line(self):
        super().on_stdout_line()
        if self.at and self.fired is None and self.count() >= self.at:
            self.fired = {"count": self.count(), "line": self.lines}
            if self.action == "stop":
                self.stop("requested")
            else:
                self.steer(self.action)
            if self.audit_key:
                threading.Thread(target=self.audit_now, daemon=True).start()

    def audit_now(self):
        k, name = self.audit_key, f"hi-run-{self.sid}"
        top = subprocess.run(["docker", "top", name, "-eo", "pid"], capture_output=True, text=True).stdout.split()[1:]
        pids = {int(p) for p in top if p.isdigit()} | {self.proc.pid}
        inside = subprocess.run(["docker", "exec", "-u", "1000", name, "sh", "-c",
                                 "cat /proc/[0-9]*/environ 2>/dev/null; env"], capture_output=True).stdout
        self.audit = {
            "docker_inspect_run": k in subprocess.run(["docker", "inspect", name], capture_output=True).stdout,
            "docker_inspect_door": k in subprocess.run(["docker", "inspect", f"hi-door-{self.sid}"],
                                                       capture_output=True).stdout,
            "host_cmdline_any": proc_hits(k, "cmdline"),
            "host_environ_run_pids": proc_hits(k, "environ", pids),
            "host_environ_any_new": proc_hits(k, "environ", None, MACHINE_VARS),
            "in_sandbox_env": k in inside,
            "key_file_readable_in_sandbox": self.secret.mode == "file",
        }


def ns(**kw):
    base = dict(folder=str(FOLDER), task="", instructions="", model="claude-sonnet-4-6", resume=None, workspace=None,
                provider_url=None, provider_api=None, key_file=str(KEYS["anthropic"]), secret="gateway", local=False,
                docker=True, timeout=600, steer_after_lines=None, stop_after_lines=None, kill_after_lines=None,
                quiet=True)
    base.update(kw)
    return argparse.Namespace(**base)


def run(label, at=None, action=None, audit_key=None, **kw):
    a = ns(**kw)
    r = WatchRun(hirun.Folder(a.folder), a, at, action, audit_key)
    t0 = time.time()
    res = r.execute()
    ws = Path(res["workspace"])
    res["wall_s"] = round(time.time() - t0, 2)
    res["trigger"] = r.fired
    res["count_final"] = r.count()
    res["done_txt"] = (ws / "done.txt").read_text().strip() if (ws / "done.txt").exists() else None
    if r.audit is not None:
        res["audit_during"] = r.audit
    if r.secret:
        res["secret_mode"] = r.secret.mode
        tok = r.secret.token.encode() if r.secret.token else None
        res["token_in_workspace"] = files_with(tok, ws) if tok else None
        res["key_in_workspace"] = files_with(r.secret.key.encode(), ws)
    events = []
    for line in (Path(res["logs"]) / "stdout.log").read_text().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(e.get("type") + (f"/{e['subtype']}" if e.get("subtype") else "") + ("+replay" if e.get("isReplay") else ""))
    res["event_counts"] = {k: events.count(k) for k in dict.fromkeys(events)}
    RUNS.mkdir(exist_ok=True)
    (RUNS / f"{label}.json").write_text(json.dumps(res, indent=2))
    brief = {k: res.get(k) for k in ("status", "answer", "resume", "steers", "steers_sent", "stop", "stop_to_exit_s",
                                       "exit_code", "seconds", "cost_usd", "trigger", "count_final", "done_txt")}
    print(f"{label}: {json.dumps(brief)[:600]}", flush=True)
    results[label] = res
    return res


def check(name, ok, evidence=None):
    results.setdefault("_checks", {})[name] = bool(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name} {json.dumps(evidence)[:300] if evidence is not None else ''}", flush=True)


def four(prefix, audit=False, **kw):
    """one-shot, resume, steer, stop + continue."""
    r = run(f"{prefix}-oneshot", task="What is 2+2?", instructions="End every answer with the code word PAPAYA.", **kw)
    check(f"{prefix} one-shot follows instructions", r["status"] == "ok" and "4" in r["answer"] and "PAPAYA" in r["answer"])
    r1 = run(f"{prefix}-resume1", task="Remember the word ORCHID. Reply OK.", **kw)
    r2 = run(f"{prefix}-resume2", task="Which word did I ask you to remember?", workspace=r1["workspace"],
             resume=r1["resume"], **kw)
    check(f"{prefix} resume", r1["status"] == r2["status"] == "ok" and "ORCHID" in r2["answer"].upper()
          and r2["resume"] == r1["resume"], {"answer": r2["answer"][:100]})
    k = key_bytes("deepseek" if "deepseek" in kw.get("key_file", "") else "anthropic") if audit else None
    s = run(f"{prefix}-steer", task=COUNT, at=3, action=STEER, audit_key=k, **kw)
    check(f"{prefix} steer", s["status"] == "ok" and s["done_txt"] == "DONE" and s["count_final"] <= 10
          and s["steers"] == 1, {"count_final": s["count_final"], "trigger": s["trigger"]})
    stop_continue(prefix, **kw)


def stop_continue(prefix, **kw):
    st = run(f"{prefix}-stop", task=COUNT, at=3, action="stop", **kw)
    time.sleep(3)
    after = len((Path(st["workspace"]) / "count.txt").read_text().split()) if st["count_final"] else 0
    c = run(f"{prefix}-continue", task=ASK, workspace=st["workspace"], resume=st["resume"], **kw)
    check(f"{prefix} stop then continue", st["status"] == "stopped" and after == st["count_final"] < 30
          and c["status"] == "ok" and re.search(r"count", c["answer"], re.I) and re.search(r"\d", c["answer"]),
          {"stop_to_exit_s": st["stop_to_exit_s"], "count_at_stop": st["trigger"], "count_after": after,
           "answer": c["answer"][:200]})


def agents_md():
    """Where 2.1.304 reads instructions: workspace AGENTS.md vs workspace CLAUDE.md vs ~/.claude/CLAUDE.md."""
    ask = "List every code word your instructions or project files give you, comma-separated, nothing else."
    for label, files, instr in (("agents-only", {"AGENTS.md": "The code word is KIWI."}, ""),
                                ("agents+home", {"AGENTS.md": "The code word is KIWI."}, "The code word is MANGO."),
                                ("agents+ws-claude+home", {"AGENTS.md": "The code word is KIWI.",
                                                           "CLAUDE.md": "The code word is FIG."}, "The code word is MANGO.")):
        ws = hirun.WORK / f"ws-agents-{label}-{os.getpid()}"
        ws.mkdir(parents=True)
        for n, t in files.items():
            (ws / n).write_text(t + "\n")
        r = run(f"local-{label}", task=ask, instructions=instr, workspace=str(ws), local=True, docker=False)
        print(f"  {label}: {r['answer']!r}")


def deepseek():
    kw = dict(provider_url="https://api.deepseek.com/anthropic", provider_api="anthropic-messages",
              key_file=str(KEYS["deepseek"]), model="deepseek-chat")
    r = run("deepseek-oneshot", task="What is 2+2?", instructions="End every answer with the code word PAPAYA.", **kw)
    check("deepseek one-shot", r["status"] == "ok" and "PAPAYA" in r["answer"], {"door": r.get("door_log")})
    r1 = run("deepseek-resume1", task="Remember the word ORCHID. Reply OK.", **kw)
    r2 = run("deepseek-resume2", task="Which word did I ask you to remember?", workspace=r1["workspace"],
             resume=r1["resume"], **kw)
    check("deepseek resume", "ORCHID" in r2["answer"].upper(), {"answer": r2["answer"][:100]})
    s = run("deepseek-steer", task=COUNT, at=3, action=STEER, **kw)
    check("deepseek steer", s["status"] == "ok" and s["done_txt"] == "DONE" and s["count_final"] <= 10,
          {"count_final": s["count_final"], "trigger": s["trigger"]})


def extras():
    """(1) what the CLI tries without CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC, behind the door;
    (2) instructions from an earlier response linger in .home/.claude/CLAUDE.md (files skips empty)."""
    import shutil
    ds = dict(provider_url="https://api.deepseek.com/anthropic", provider_api="anthropic-messages",
              key_file=str(KEYS["deepseek"]), model="deepseek-chat")
    loud = hirun.WORK / "claude-code-loud" / "claude-code"
    shutil.rmtree(loud.parent, ignore_errors=True)
    shutil.copytree(FOLDER, loud, ignore=shutil.ignore_patterns("proof", "__pycache__"))
    rs = (loud / "run.sh").read_text().replace("export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1", ": loud")
    (loud / "run.sh").write_text(rs)
    for mode in ("file", "gateway"):
        r = run(f"loud-{mode}", folder=str(loud), task="What is 2+2?", secret=mode, **ds)
        check(f"loud {mode}: other hosts denied, run unharmed", r["status"] == "ok", {"door": sorted(set(r.get("door_log", [])))})
    r1 = run("stale-1", task="What is 2+2?", instructions="End every answer with the code word PAPAYA.", **ds)
    r2 = run("stale-2", task="What is 3+3?", workspace=r1["workspace"], resume=r1["resume"], **ds)
    lingering = (Path(r1["workspace"]) / ".home/.claude/CLAUDE.md").exists()
    check("instructions linger after a response without them", lingering, {"answer2": r2["answer"][:80]})


def audit():
    """After every run: search each place a key could have landed (never printing it)."""
    out = {}
    tools = sorted(p for p in hirun.TOOLS.glob("claude-code-*") if p.is_dir())
    wss = sorted({json.loads(p.read_text())["workspace"] for p in RUNS.glob("*.json")})
    logs = sorted({json.loads(p.read_text())["logs"] for p in RUNS.glob("*.json")})
    base = hirun.Base().tag
    for name in KEYS:
        k = key_bytes(name)
        p = subprocess.Popen(["docker", "save", base], stdout=subprocess.PIPE)
        tail, img = b"", False
        while chunk := p.stdout.read(1 << 20):
            img = img or k in tail + chunk
            tail = chunk[-len(k):]
        p.wait()
        out[name] = {
            "base_image": img,
            "tools_dirs": {t.name: files_with(k, t) for t in tools},
            "install_logs": [t.name for t in hirun.TOOLS.glob("claude-code-*.install.log") if k in t.read_bytes()],
            "workspaces_and_home": {w: files_with(k, Path(w)) for w in wss if files_with(k, Path(w))},
            "run_logs": {lg: files_with(k, Path(lg)) for lg in logs if files_with(k, Path(lg))},
            "proof_dir": files_with(k, HERE),
            "host_cmdline": proc_hits(k, "cmdline"),
            "host_environ_beyond_machine_vars": proc_hits(k, "environ", None, machine_vars(k)),
            "machine_vars_holding_it": sorted(machine_vars(k)),
            "hi_containers_left": subprocess.run(["docker", "ps", "-aq", "--filter", "name=^hi-"],
                                                 capture_output=True, text=True).stdout.split(),
            "shm_left": [str(p) for p in Path("/dev/shm").glob("hi-*")],
        }
    out["checked"] = {"tools_dirs": [t.name for t in tools], "workspaces": len(wss), "run_logs": len(logs),
                      "image": base}
    print(json.dumps(out, indent=1))
    results["audit"] = out


def main():
    global MACHINE_VARS
    group = sys.argv[1]
    MACHINE_VARS = machine_vars(key_bytes("anthropic"))
    if group == "local":
        four("local", local=True, docker=False)
        agents_md()
    elif group == "docker":
        mode = sys.argv[2]
        if mode == "gateway":
            t = hirun.Tools(hirun.Folder(FOLDER), False)
            t0 = time.time(); _, hit1 = t.ensure(); t1 = time.time(); _, hit2 = t.ensure(); t2 = time.time()
            results["install"] = {"first": "hit" if hit1 else "miss", "first_s": round(t1 - t0, 1),
                                  "second": "hit" if hit2 else "miss", "second_s": round(t2 - t1, 2), "dir": t.dir.name}
            print("install", results["install"], flush=True)
        four(f"docker-{mode}", audit=True, secret=mode)
    elif group == "deepseek":
        deepseek()
    elif group == "deepseek-file":           # Anthropic credit ran out mid-proof: file mode's stop on DeepSeek
        kw = dict(provider_url="https://api.deepseek.com/anthropic", provider_api="anthropic-messages",
                  key_file=str(KEYS["deepseek"]), model="deepseek-chat", secret="file")
        r = run("deepseek-file-oneshot", task="What is 2+2?", instructions="End every answer with the code word PAPAYA.", **kw)
        check("deepseek-file one-shot", r["status"] == "ok" and "PAPAYA" in r["answer"], {"door": r.get("door_log")})
        stop_continue("deepseek-file", **kw)
    elif group == "extras":
        extras()
    elif group == "audit":
        audit()
    name = "-".join(sys.argv[1:])
    (HERE / f"results-{name}.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
