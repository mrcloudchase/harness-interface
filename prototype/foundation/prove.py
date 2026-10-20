#!/usr/bin/env python3
"""End-to-end proofs of the foundation, black-box through hirun.py. Writes proof/proof.json and
prints one line per check. Keys are loaded only to grep for them; never printed.

    python3 prove.py            # everything (~2 min)
    python3 prove.py secrets    # only the secrets matrix
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HIRUN = [sys.executable, str(ROOT / "hirun.py")]
SECRETS = Path("/home/user/harness-interface/data/secrets")
WORK = ROOT / "work" / "proof"
results: dict = {}


CLEAN_ENV = {k: v for k, v in os.environ.items() if not re.search(r"KEY|TOKEN|SECRET|^CLAUDE|^CCR|^ANTHROPIC|^OPENAI", k)}


def hirun(*args, timeout=300) -> dict:
    r = subprocess.run([*HIRUN, *args, "--quiet"] if args[0] == "run" else [*HIRUN, *args],
                       capture_output=True, text=True, timeout=timeout, env=CLEAN_ENV)
    if r.returncode != 0:
        raise RuntimeError(f"hirun {args[:2]} failed: {r.stderr[-800:]}")
    return json.loads(r.stdout)


def check(name: str, ok: bool, evidence) -> None:
    results[name] = {"ok": bool(ok), "evidence": evidence}
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {json.dumps(evidence)[:220]}", flush=True)


def leftovers() -> dict:
    ps = subprocess.run(["docker", "ps", "-aq", "--filter", "name=^hi-"], capture_output=True, text=True).stdout.split()
    nets = subprocess.run(["docker", "network", "ls", "-q", "--filter", "name=^hi-net-"], capture_output=True,
                          text=True).stdout.split()
    return {"containers": len(ps), "networks": len(nets), "shm_keys": len(list(Path("/dev/shm").glob("hi-*")))}


def stubborn() -> Path:
    """The template, but its adapter ignores a stop: proves the kill after run.stop_timeout_s."""
    d = WORK / "stubborn"
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(ROOT / "template", d)
    spec = json.loads((d / "harness.json").read_text())
    spec["name"], spec["run"]["stop_timeout_s"] = "stubborn", 2
    (d / "harness.json").write_text(json.dumps(spec, indent=2))
    a = (d / "adapter.py").read_text()
    a = a.replace('        self.send({"type": "abort"})', '        pass                                         # stubborn')
    (d / "adapter.py").write_text(a.replace("stop_grace_s = 10.0", "stop_grace_s = 60.0"))
    return d


def basics() -> None:
    t = str(ROOT / "template")
    for local in (False, True):
        flag = ["--local"] if local else []
        tools = hirun("install", t, *flag)["tools"]
        shutil.rmtree(tools)
        Path(tools).with_suffix(".install.log").unlink(missing_ok=True)
        t0 = time.time()
        miss = hirun("install", t, *flag)
        t1 = time.time()
        hit = hirun("install", t, *flag)
        check(f"install cache {'local' if local else 'docker'}", miss["cache"] == "miss" and hit["cache"] == "hit",
              {"miss_s": round(t1 - t0, 1), "hit_s": round(time.time() - t1, 2), "tools": Path(tools).name})
    for mode in ("--local", "--docker"):
        r = hirun("run", t, mode, "--task", "count to 6", "--steer-after-lines", "4", "count to 8 instead")
        check(f"steer lands {mode}", r["status"] == "ok" and r["steers"] == 1 and r["answer"] == "Counted to 8."
              and r["files_changed"]["added"] == ["count.txt"],
              {k: r[k] for k in ("status", "answer", "steers", "steers_sent", "seconds")})
    for mode in ("--local", "--docker"):
        ws = WORK / f"stop{mode}"
        shutil.rmtree(ws, ignore_errors=True)
        r = hirun("run", t, mode, "--task", "count to 30", "--stop-after-lines", "5", "--workspace", str(ws))
        check(f"SIGINT stop is graceful {mode}", r["status"] == "stopped" and r["stop"] == "requested"
              and r["exit_code"] == 0 and r["stop_to_exit_s"] < 2,
              {k: r[k] for k in ("status", "answer", "stop", "stop_to_exit_s", "exit_code")})
        r2 = hirun("run", t, mode, "--task", "continue, count to 8", "--resume", r["resume"], "--workspace", str(ws))
        counted = (ws / "count.txt").read_text().split()
        check(f"continued run resumes {mode}", r2["status"] == "ok" and r2["resume"] == r["resume"]
              and counted == [str(i) for i in range(1, 9)], {"answer": r2["answer"], "count.txt": counted})
    s = stubborn()
    r = hirun("run", str(s), "--task", "count to 30", "--stop-after-lines", "4")
    check("stop timeout kills (adapter ignores SIGINT)", r["stop"] == "requested+killed"
          and 1.5 < r["stop_to_exit_s"] < 6 and r["resume"],
          {k: r[k] for k in ("status", "stop", "stop_to_exit_s", "exit_code", "resume")})
    ws = WORK / "kill"
    shutil.rmtree(ws, ignore_errors=True)
    r = hirun("run", t, "--task", "count to 30", "--kill-after-lines", "6", "--workspace", str(ws))
    out = json.loads((Path(r["logs"]) / "output.json").read_text())
    session = json.loads(next((ws / ".home/.standin/sessions").glob("*.json")).read_text())
    check("resume id written early, survives a kill", out["status"] == "running" and out["resume"] == r["resume"]
          and session["count"] >= 3, {"output.json": out, "saved_count": session["count"], "status": r["status"]})
    r2 = hirun("run", t, "--task", "continue, count to 8", "--resume", r["resume"], "--workspace", str(ws))
    counted = (ws / "count.txt").read_text().split()
    check("killed session resumes", r2["status"] == "ok" and counted == [str(i) for i in range(1, 9)],
          {"answer": r2["answer"], "count.txt": counted})


def egress() -> None:
    p = str(ROOT / "probe")
    tools = Path(hirun("install", p)["tools"])
    inst = json.loads((tools / "install_egress.json").read_text())
    c = inst["connect"]
    check("install container: only install.egress", c["registry.npmjs.org"].startswith("200")
          and all(v.startswith("403") for h, v in c.items() if h != "registry.npmjs.org")
          and (tools / "provider_vars.txt").read_text().strip() == "0", inst)
    r = hirun("run", p, "--task", "probe", "--key-file", str(SECRETS / "ANTHROPIC_API_KEY"), "--secret", "file")
    a = json.loads(r["answer"])
    c = a["connect"]
    check("run container: only the provider (CONNECT door, api.anthropic.com)",
          c["api.anthropic.com"].startswith("200") and all(v.startswith("403") for h, v in c.items()
                                                            if h != "api.anthropic.com")
          and all("Errno" in v for v in a["direct"].values()) and a["provider_with_key"] == 200
          and a["loopback"] == 200,
          {"connect": c, "direct": a["direct"], "dns": a["dns"], "with_key": a["provider_with_key"],
           "loopback_with_proxy_env": a["loopback"]})
    r = hirun("run", p, "--task", "probe", "--key-file", str(SECRETS / "ANTHROPIC_API_KEY"), "--secret", "gateway")
    a = json.loads(r["answer"])
    check("run container, gateway: no CONNECT at all, provider via gateway",
          all(v.startswith("403") for v in a["connect"].values()) and a["provider_with_key"] == 200
          and a["provider_no_key"] == 401, {"connect": a["connect"], "with_token": a["provider_with_key"],
                                            "without": a["provider_no_key"], "door_log": r["door_log"]})
    r = hirun("run", p, "--task", "probe", "--key-file", str(SECRETS / "OPENAI_API_KEY"), "--secret", "gateway",
              "--provider-url", "https://api.openai.com", "--provider-api", "openai-responses")
    a = json.loads(r["answer"])
    check("gateway, openai shape (Bearer swap)", a["provider_with_key"] == 200, {"with_token": a["provider_with_key"]})
    r = hirun("run", p, "--task", "stream", "--model", "claude-sonnet-4-6", "--key-file",
              str(SECRETS / "ANTHROPIC_API_KEY"), "--secret", "gateway")
    a = json.loads(r["answer"])
    check("gateway streams SSE", a["events"] > 5 and a["last_s"] > a["first_s"], a)


# --- secrets ---------------------------------------------------------------------------------
def proc_hits(key: bytes, what: str, ignore: frozenset = frozenset()) -> list[str]:
    """Host processes whose /proc/<pid>/<what> holds the key, as "comm" or "comm:VAR" for environ.
    This prover is excluded, and so are variables named in `ignore`: this machine starts dockerd
    and containerd with the key in its own variable, which every containerd-shim inherits."""
    hits = []
    for d in Path("/proc").glob("[0-9]*"):
        if d.name == str(os.getpid()):
            continue
        try:
            data = (d / what).read_bytes()
            comm = (d / "comm").read_text().strip()
        except OSError:
            continue
        if what == "environ":
            hits += [f"{comm}:{kv.split(b'=')[0].decode()}" for kv in data.split(b"\0")
                     if key in kv and kv.split(b"=")[0].decode() not in ignore]
        elif key in data:
            hits.append(comm)
    return sorted(set(hits))


def tree_has(key: bytes, path: Path) -> bool:
    for root, _, files in os.walk(path):
        for n in files:
            try:
                if key in Path(root, n).read_bytes():
                    return True
            except OSError:
                pass
    return False


def image_has(key: bytes, image: str) -> bool:
    p = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE)
    tail, found = b"", False
    while chunk := p.stdout.read(1 << 20):
        if key in tail + chunk:
            found = True
        tail = chunk[-len(key):]
    p.wait()
    return found


def machine_vars(key: bytes) -> frozenset:
    """Variables that already hold the key on this machine before any run (not ours)."""
    return frozenset(h.split(":", 1)[1] for h in proc_hits(key, "environ")) - {"HI_PROVIDER_KEY", "STANDIN_API_KEY"}


def secret_case(mode: str, key: bytes) -> dict:
    base = machine_vars(key)
    args = [*HIRUN, "run", str(ROOT / "template"), "--task", "count to 14", "--secret", mode,
            "--key-file", str(SECRETS / "ANTHROPIC_API_KEY")]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=CLEAN_ENV)
    err_lines, seen = [], threading.Event()

    def read():
        for line in proc.stderr:
            err_lines.append(line)
            if '"type": "provider"' in line:
                seen.set()
    threading.Thread(target=read, daemon=True).start()
    assert seen.wait(60), "no provider event"
    name = subprocess.run(["docker", "ps", "--format", "{{.Names}}", "--filter", "name=^hi-run-"],
                          capture_output=True, text=True).stdout.split()[0]
    sid = name[len("hi-run-"):]
    during = {
        "docker_inspect_run": key in subprocess.run(["docker", "inspect", name], capture_output=True).stdout,
        "docker_inspect_door": key in subprocess.run(["docker", "inspect", f"hi-door-{sid}"], capture_output=True).stdout,
        "host_cmdline": proc_hits(key, "cmdline", base),
        "host_environ": proc_hits(key, "environ", base),
        "readable_in_sandbox": key in subprocess.run(
            ["docker", "exec", "-u", "1000", name, "sh", "-c",
             "cat /proc/[0-9]*/environ /dev/shm/hi-*/key 2>/dev/null; env; true"], capture_output=True).stdout,
    }
    out, _ = proc.communicate(timeout=120)
    r = json.loads(out)
    provider = [json.loads(ln.split("] ", 1)[1]) for ln in err_lines if '"type": "provider"' in ln][0]
    after = {
        "provider_status": provider.get("status"),
        "run_status": r["status"],
        "workspace_and_home": tree_has(key, Path(r["workspace"])),
        "tools_dir": tree_has(key, Path(r["tools"])),
        "run_logs": tree_has(key, Path(r["logs"])),
        "runner_output": key in (out + "".join(err_lines)).encode(),
        "host_environ_after": proc_hits(key, "environ", base),
        "leftovers": leftovers(),
    }
    return {"during": during, "after": after}


def secrets() -> None:
    key = (SECRETS / "ANTHROPIC_API_KEY").read_bytes().strip()
    matrix = {mode: secret_case(mode, key) for mode in ("env", "file", "gateway")}
    results["secrets_matrix"] = matrix
    for mode, m in matrix.items():
        print(f"secrets {mode}: {json.dumps(m)}", flush=True)
    base = subprocess.run([*HIRUN, "base"], capture_output=True, text=True).stdout
    check("key never in the base image", not image_has(key, json.loads(base)["tag"]), json.loads(base)["tag"])
    g = matrix["gateway"]
    check("gateway: key nowhere but the door", g["after"]["provider_status"] == 200
          and not any(v for k, v in g["during"].items()) and not any(
              v for k, v in g["after"].items() if k not in ("provider_status", "run_status", "leftovers")), g)


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1:] or ["basics", "egress", "secrets"]
    for step in which:
        globals()[step]()
    left = leftovers()
    check("teardown leaves nothing", not any(left.values()), left)
    path = ROOT / "proof" / f"proof-{'-'.join(which)}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(results, indent=2))
    failed = [k for k, v in results.items() if isinstance(v, dict) and v.get("ok") is False]
    print(f"{len(failed)} failed{': ' + ', '.join(failed) if failed else ''}; written {path}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
