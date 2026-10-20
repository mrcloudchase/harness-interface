#!/usr/bin/env python3
"""The live suite: one harness folder against a real provider, sandboxed, driven from the library (no
server) and from the HTTP API (the server as a subprocess), under the gateway and with a key file.
Run it to prove a folder, and before every release:

    uv run --extra dev python scripts/live.py harnesses/claude-code \\
        --url https://api.deepseek.com/anthropic --api anthropic-messages \\
        --key-file data/secrets/DEEPSEEK_API_KEY --model deepseek-chat --ca-file /root/.ccr/ca-bundle.crt

For each way in (`--via library,api`) and credential mode (`--credential gateway,file`) it runs four
sessions at once, then audits what they left:

  install    the first install is a miss, the next a cached hit (the tools directory is new, then reused)
  one-shot   it follows its instructions (they reach it only through the folder's `files`)
  usage      it reports input and output tokens
  config     every example config artifact in the folder's home/ was loaded (below)
  resume     a continued session remembers a word (ORCHID) from the response before
  reported   the memory it wrote comes back as a reported artifact (folders with `report`)
  steer      counting to 30 with sleeps, steered once count.txt holds 3 numbers: done.txt, far fewer than 30
  stop       stopped once count.txt holds 3 numbers, then continued by an interrupt: it says what it was
             doing and how far it got
  secrets    the key is in no record, log, workspace or .home, nothing served, no `docker inspect`, no
             process inside the sandbox, no host process the runs started, and no new host process at all

A folder proves its config artifacts by naming each example `hi-live-<kind>` (`hi-live-skill`,
`hi-live-mcp`, `hi-live-hook`, …). Every such name in its home/ must then show in a response's stdout or
reported artifacts, which only an artifact the CLI loaded can make happen.

Steers and stops are cued on the workspace's count.txt, read at every line of output, never on line
counts. It prints a table, keeps the evidence in <data>/live.json, and exits 1 if anything failed. The
key is read from its file and never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from harness_interface import Ask, HarnessFolder, Images, Placement, ProviderEntry, Sessions
from harness_interface.runtimes.process import host_env
from harness_interface.store import decode, folder_map

PROVIDER = "live"
INSTRUCTIONS = "End every answer with the code word PAPAYA."
ONE_SHOT = "What is 2+2?"
REMEMBER = "Remember the word ORCHID: save it to your memory. Reply OK."
RECALL = "Which word did I ask you to remember? Reply with the word only."
COUNT = ("Using the shell, write the numbers 1 to 30 to count.txt, one per line, running `sleep 1` between each "
         "number (one shell command per number). Do not write them all at once.")
STEER = "Stop counting now. Instead write the word DONE into done.txt and finish."
ASK = "What were you doing before you were stopped, and how far did you get? One sentence; do not continue the task."
MARKER = re.compile(r"hi-live-[a-z]+")
CHECKS = ("install", "one-shot", "usage", "config", "resume", "reported", "steer", "stop", "secrets")


@dataclass
class Got:
    """A response once it has ended, whichever way it came."""
    id: str
    session: str
    status: str
    answer: str
    resume: str | None
    usage: dict
    home: dict                                       # reported artifacts: path -> text, None if deleted
    stdout: str
    steers: int                                      # the steers the harness took
    stop: str | None


def text(content) -> str | None:
    return None if content is None else decode(content).decode(errors="replace")


def count(workspace: Path) -> int:
    try:
        return len((workspace / "count.txt").read_text().split())
    except OSError:
        return 0


def read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


class Library:
    """The library, no server: `Sessions` in this process."""

    def __init__(self, data: Path, placement: Placement):
        self.s = Sessions(data, placement)
        self.served: list[str] = []                  # nothing is served

    async def provider(self, entry: ProviderEntry) -> None:
        self.s.registry.put_provider(entry)

    async def install(self, name: str, files: dict) -> None:
        await self.s.registry.put_harness(name, files)
        await self.s.registry.ready(name)

    async def start(self, model, task, instructions="", previous=None, cue=None) -> Got:
        session = await self.s.start(Ask(model, task, instructions=instructions, previous=previous))
        rid = session.responses[-1]
        async for event in self.s.follow(rid):
            if cue and event.kind == "stdout":
                await cue(session.id)
        return await self.wait(rid)

    async def interrupt(self, sid: str, text_: str) -> tuple[str, str]:
        outcome, record = await self.s.interrupt(sid, text_)
        return outcome, record.id

    async def stop(self, sid: str) -> str:
        return await self.s.stop(sid)

    async def wait(self, rid: str, sid: str | None = None) -> Got:
        r = await self.s.wait(rid)
        a = self.s.artifacts(rid)
        return Got(r.id, r.session, r.status, r.answer, r.resume, r.usage,
                   {p: None if c is None else c.decode(errors="replace") for p, c in a.home.items()},
                   a.stdout.decode(errors="replace"), r.output.get("steers", 0), r.stop)

    async def close(self) -> None:
        await self.s.close()


class Api:
    """The HTTP API: the server's own entry point as a subprocess, with only allowlisted variables."""

    def __init__(self, proc: subprocess.Popen, port: int):
        self.proc = proc
        self.http = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=None)
        self.served: list[str] = []                  # every body it sent, for the audit

    @classmethod
    async def open(cls, data: Path, local: bool, ca_file: Path | None) -> Api:
        with socket.create_server(("127.0.0.1", 0)) as s:
            port = s.getsockname()[1]
        env = {**host_env(), "HI_DATA_DIR": str(data), "HI_PORT": str(port),
               "HI_RUNTIME": "local" if local else "docker", **({"HI_CA_FILE": str(ca_file)} if ca_file else {})}
        log = open(data / "server.log", "ab")
        proc = subprocess.Popen([str(Path(sys.executable).with_name("harness-interface"))], env=env, stdout=log,
                                stderr=subprocess.STDOUT)
        api = cls(proc, port)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                await api.http.get("/providers")
                return api
            except httpx.TransportError:
                await asyncio.sleep(0.2)
        raise RuntimeError(f"the server did not start: see {data / 'server.log'}")

    async def call(self, method: str, path: str, **kw) -> dict:
        r = await self.http.request(method, path, **kw)
        self.served.append(r.text)
        if r.status_code != 200:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:300]}")
        return r.json()

    async def provider(self, entry: ProviderEntry) -> None:
        await self.call("PUT", f"/providers/{entry.name}", json={"url": entry.url, "api": entry.api, "key": entry.key})

    async def install(self, name: str, files: dict) -> None:
        state = (await self.call("PUT", f"/harnesses/{name}", json=files))["install"]["state"]
        while state == "installing":
            await asyncio.sleep(0.5)
            state = next(h for h in await self.call("GET", "/harnesses") if h["name"] == name)["install"]["state"]
        if state != "ready":
            raise RuntimeError(f"install {state}")

    async def start(self, model, task, instructions="", previous=None, cue=None) -> Got:
        body = {"model": model, "input": task, "instructions": instructions or None,
                "previous_response_id": previous, "stream": True}
        async with self.http.stream("POST", "/responses", json=body) as r:
            if r.status_code != 200:
                raise RuntimeError(f"POST /responses: {r.status_code} {(await r.aread())[:300]!r}")
            sid, rid = r.headers["x-session-id"], r.headers["x-response-id"]
            async for line in r.aiter_lines():
                self.served.append(line)
                if cue and line.startswith("data: ") and '"type": "harness.stdout"' in line:
                    await cue(sid)
        return await self.wait(rid, sid)

    async def interrupt(self, sid: str, text_: str) -> tuple[str, str]:
        j = await self.call("POST", f"/sessions/{sid}/interrupt", json={"input": text_})
        return j["outcome"], j["response"]["id"]

    async def stop(self, sid: str) -> str:
        return (await self.call("POST", f"/sessions/{sid}/stop", json={}))["outcome"]

    async def wait(self, rid: str, sid: str | None = None) -> Got:
        while True:                                  # a finished stream or interrupt has it ended already
            r = next(x for x in (await self.call("GET", f"/sessions/{sid}"))["responses"] if x["id"] == rid)
            if r["status"] != "in_progress":
                break
            await asyncio.sleep(0.5)
        h = r["harness"]
        answer = r["output"][0]["content"][0]["text"] if r["output"] else ""
        return Got(r["id"], h["session"], r["status"], answer, h["resume"], h["usage"],
                   {p: text(c) for p, c in h["home"].items()}, h["stdout"], h["output"].get("steers", 0), h["stop"])

    async def close(self) -> None:
        for s in (await self.call("GET", "/sessions"))["data"]:          # everything it serves, for the audit
            await self.call("GET", f"/sessions/{s['id']}")
        await self.call("GET", "/providers")
        await self.http.aclose()
        self.proc.send_signal(signal.SIGINT)                               # its shutdown stops what still runs
        await asyncio.to_thread(self.proc.wait, 120)


# the audit
def holders(key: bytes) -> dict[int, tuple[bool, set[str]]]:
    """Every process whose command line holds the key, or names in its environment that do."""
    found = {}
    for d in Path("/proc").glob("[0-9]*"):
        try:
            cmdline, environ = (d / "cmdline").read_bytes(), (d / "environ").read_bytes()
        except OSError:
            continue
        names = {kv.split(b"=", 1)[0].decode(errors="replace") for kv in environ.split(b"\0") if key in kv}
        if key in cmdline or names:
            found[int(d.name)] = (key in cmdline, names)
    return found


def family(roots: set[int]) -> set[int]:
    """The processes in `roots` and every one descended from them."""
    parent = {}
    for d in Path("/proc").glob("[0-9]*"):
        try:
            parent[int(d.name)] = int((d / "stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            continue
    out, grew = set(roots), True
    while grew:
        more = {p for p, pp in parent.items() if pp in out} - out
        out |= more
        grew = bool(more)
    return out


def docker_out(*args: str) -> bytes:
    return subprocess.run(["docker", *args], capture_output=True, env=host_env()).stdout


def live_audit(key: bytes, mode: str, before: set[str], docker: bool) -> list[str]:
    """While the runs are live: the containers, what runs in them, and the host's processes."""
    problems, pids = [], set()
    names = docker_out("ps", "--filter", "name=hi-", "--format", "{{.Names}}").decode().split() if docker else []
    for name in names:
        if key in docker_out("inspect", name):
            problems.append(f"docker inspect {name}")
        pid = docker_out("inspect", "-f", "{{.State.Pid}}", name).decode().strip()
        pids |= {int(pid)} if pid.isdigit() else set()
        if name.startswith("hi-run-"):
            inside = docker_out("exec", "-u", "1000", name, "sh", "-c", "cat /proc/[0-9]*/environ; env")
            if key in inside:
                problems.append(f"environment inside {name}")
            if mode == "gateway" and key in docker_out("exec", "-u", "1000", name, "cat", "/run/hi/key"):
                problems.append(f"the key file in {name} holds the key, not a token")
    ours = family({os.getpid()} | pids) - {os.getpid()}                 # this process inherited the machine's
    for pid, (in_cmdline, env_names) in holders(key).items():
        if pid == os.getpid():
            continue
        if in_cmdline:
            problems.append(f"command line of pid {pid}")
        if env_names and (pid in ours or env_names - before):
            problems.append(f"environment of pid {pid}: {sorted(env_names)}")
    return problems


def files_with(key: bytes, root: Path) -> list[str]:
    """Every file under the data directory holding the key, but the provider it was registered as."""
    return [str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() and not p.is_symlink()
            and p.relative_to(root).parts[0] != "providers" and key in p.read_bytes()]


# the scenarios
class Suite:
    def __init__(self, args: argparse.Namespace):
        self.args, self.folder = args, HarnessFolder.load(Path(args.folder))
        self.key = Path(args.key_file).read_text().strip()
        self.data = Path(args.data or tempfile.mkdtemp(prefix="hi-live-")).absolute()
        self.data.mkdir(parents=True, exist_ok=True)
        self.model = f"{self.folder.name}@{PROVIDER}" + (f"/{args.model}" if args.model else "")
        home = self.folder.home
        self.markers = {m for p in home.rglob("*") if p.is_file()
                        for m in MARKER.findall(p.as_posix() + p.read_text(errors="replace"))} if home else set()
        self.before = {n for _, names in holders(self.key.encode()).values() for n in names}
        self.results: dict[str, dict[str, tuple[bool | None, str]]] = {}

    def files(self, credential: str) -> dict:
        files = folder_map(self.folder.path)
        spec = json.loads(files["harness.json"])
        spec["run"]["credential"] = credential
        return {**files, "harness.json": json.dumps(spec, indent=2)}

    def tools(self) -> set[Path]:
        return set((self.data / "tools").glob(f"{self.folder.name}-*/.hi-installed"))

    async def driver(self, via: str):
        ca = Path(self.args.ca_file) if self.args.ca_file else None
        if via == "api":
            return await Api.open(self.data, self.args.local, ca)
        return Library(self.data, Placement(None if self.args.local else Images(self.data / "logs"), ca_file=ca))

    async def run(self, via: str, credential: str) -> dict[str, tuple[bool | None, str]]:
        d = await self.driver(via)
        out: dict[str, tuple[bool | None, str]] = {}
        try:
            await d.provider(ProviderEntry(PROVIDER, self.args.url, self.args.api, self.key))
            try:
                out["install"] = await self.install(d, credential)
            except Exception as e:  # noqa: BLE001 - nothing runs without it, and the rest say so
                return {"install": (False, f"{type(e).__name__}: {e}")}
            jobs = {("one-shot", "usage", "config"): self.one_shot(d), ("resume", "reported"): self.resume(d),
                    ("steer",): self.steer(d, credential), ("stop",): self.stop(d)}
            done = await asyncio.gather(*(asyncio.wait_for(j, self.args.timeout) for j in jobs.values()),
                                        return_exceptions=True)
            for names, got in zip(jobs, done):
                for name in names:
                    out[name] = (got.get(name, (None, "")) if isinstance(got, dict)
                                 else (False, f"{type(got).__name__}: {got}"))
        finally:
            await d.close()
        problems = self.audits + ([] if self.audited else ["no live audit: no session was steered"])
        problems += files_with(self.key.encode(), self.data)
        problems += [f"served by the API: {i}" for i, body in enumerate(d.served) if self.key in body]
        out["secrets"] = (not problems, "; ".join(problems) or "the key is nowhere it shouldn't be")
        return out

    async def install(self, d, credential: str) -> tuple[bool, str]:
        said, ok = [], True
        for attempt in range(2 if not self.tools() else 1):              # a fresh data directory: miss, then hit
            had, t = self.tools(), time.monotonic()
            await d.install(self.folder.name, self.files(credential))
            hit = bool(had) and self.tools() == had
            said.append(f"{'hit' if hit else 'miss'} {time.monotonic() - t:.1f}s")
            ok = ok and hit == (attempt == 1 or bool(had))
        return ok, " -> ".join(said)

    async def one_shot(self, d) -> dict:
        g = await d.start(self.model, ONE_SHOT, INSTRUCTIONS)
        seen = g.stdout + json.dumps(g.home)
        found = {m for m in self.markers if m in seen}
        u = g.usage
        return {"one-shot": (g.status == "completed" and "4" in g.answer and "PAPAYA" in g.answer.upper(),
                             f"{g.status}: {g.answer[:80]!r}"),
                "usage": (u.get("input_tokens", 0) > 0 and u.get("output_tokens", 0) > 0, json.dumps(u)[:160]),
                "config": (found == self.markers, f"loaded {sorted(found)} of {sorted(self.markers)}")
                if self.markers else (None, "no hi-live-* example in home/")}

    async def resume(self, d) -> dict:
        a = await d.start(self.model, REMEMBER)
        b = await d.start(self.model, RECALL, previous=a.id)
        home = {**a.home, **b.home}
        return {"resume": (a.status == b.status == "completed" and "ORCHID" in b.answer.upper()
                           and a.session == b.session and bool(a.resume) and b.resume == a.resume,
                           f"{b.status}: {b.answer[:80]!r}"),
                "reported": (any("ORCHID" in (c or "").upper() for c in home.values()), f"home: {sorted(home)}")
                if self.folder.report else (None, "the folder reports nothing")}

    async def steer(self, d, credential: str) -> dict:
        fired: dict = {}

        async def cue(sid: str) -> None:
            if not fired and count(self.data / "workspaces" / sid) >= 3:
                fired["at"] = count(self.data / "workspaces" / sid)
                fired["outcome"], _ = await d.interrupt(sid, STEER)
                self.audits += await asyncio.to_thread(live_audit, self.key.encode(), credential, self.before,
                                                       not self.args.local)
                self.audited = True
        g = await d.start(self.model, COUNT, cue=cue)
        ws = self.data / "workspaces" / g.session
        done, n = read(ws / "done.txt"), count(ws)
        return {"steer": (g.status == "completed" and fired.get("outcome") == "steered" and done == "DONE"
                          and n <= 10 and g.steers >= 1,
                          f"{g.status}, steered at {fired.get('at')} ({fired.get('outcome')}), counted {n}, "
                          f"done.txt {done!r}, steers taken {g.steers}")}

    async def stop(self, d) -> dict:
        fired: dict = {}

        async def cue(sid: str) -> None:
            if not fired and count(self.data / "workspaces" / sid) >= 3:
                fired["at"], t = count(self.data / "workspaces" / sid), time.monotonic()
                fired["outcome"] = await d.stop(sid)
                fired["took"] = time.monotonic() - t
        g = await d.start(self.model, COUNT, cue=cue)
        at_stop = count(self.data / "workspaces" / g.session)
        outcome, rid = await d.interrupt(g.session, ASK)
        c = await d.wait(rid, g.session)
        return {"stop": (fired.get("outcome") == "stopped" and g.status == "cancelled" and g.stop == "stopped"
                         and bool(g.resume) and 3 <= at_stop < 30 and outcome == "continued"
                         and c.status == "completed" and c.resume == g.resume
                         and bool(re.search(r"count|number", c.answer, re.I) and re.search(r"\d", c.answer)),
                         f"{fired.get('outcome')} at {fired.get('at')} in {fired.get('took', 0):.1f}s, "
                         f"{g.status}/{g.stop}, counted {at_stop}; {outcome}: {c.answer[:120]!r}")}

    async def main(self) -> int:
        for via in self.args.via.split(","):
            for credential in self.args.credential.split(","):
                self.audits: list[str] = []
                self.audited = False
                column = f"{via}/{credential}"
                print(f"running {column} ...", flush=True)
                self.results[column] = await self.run(via, credential)
        (self.data / "live.json").write_text(json.dumps(self.results, indent=2))
        return self.report()

    def report(self) -> int:
        columns = list(self.results)
        word = {True: "PASS", False: "FAIL", None: "-"}
        print(f"\n{self.folder.name} on {self.args.url} ({self.args.api}, {self.args.model or 'default model'})"
              f"{', local' if self.args.local else ', sandboxed'}; data {self.data}\n")
        print(f"{'check':10}" + "".join(f"{c:18}" for c in columns))
        for check in CHECKS:
            print(f"{check:10}" + "".join(f"{word[self.results[c].get(check, (False, ''))[0]]:18}" for c in columns))
        print()
        for c in columns:
            for check in CHECKS:
                ok, evidence = self.results[c].get(check, (False, "not run"))
                print(f"{c:16} {check:9} {word[ok]:4}  {evidence}")
        failed = any(r.get(check, (False,))[0] is False for r in self.results.values() for check in CHECKS)
        print(f"\n{'FAILED' if failed else 'PASSED'}")
        return 1 if failed else 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder", help="the harness folder")
    p.add_argument("--url", required=True, help="the provider's base URL, as the shape's official SDK takes it")
    p.add_argument("--api", required=True, help="anthropic-messages, openai-responses or openai-chat")
    p.add_argument("--key-file", required=True, help="a file holding the provider's key")
    p.add_argument("--model", default="", help="the model to ask for; the harness's own by default")
    p.add_argument("--via", default="library,api", help="library, api, or both (the default)")
    p.add_argument("--credential", default="gateway,file", help="gateway, file, or both (the default)")
    p.add_argument("--ca-file", default=os.environ.get("HI_CA_FILE"),
                   help="a CA bundle, where the network re-signs TLS")
    p.add_argument("--data", help="the data directory (default: a new one, so the first install is a miss)")
    p.add_argument("--local", action="store_true", help="run on this machine, unsandboxed (developing a folder)")
    p.add_argument("--timeout", type=float, default=900, help="seconds each session may take")
    sys.exit(asyncio.run(Suite(p.parse_args()).main()))


if __name__ == "__main__":
    main()
