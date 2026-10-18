"""`hi`: the command line for harness-interface. Every command is a call to the API, except
`hi server`, which starts and stops the server itself.

    hi server start | stop | status | logs
    hi provider add NAME --url URL [--key-env VAR] | ls | show NAME | rm NAME
    hi sandbox  add NAME DOCKERFILE [--egress HOST ...] | ls | show NAME | rm NAME
    hi harness  add FOLDER ... | add --builtin [NAME ...] | ls | show NAME | rm NAME
    hi run HARNESS[/MODEL] TASK [-f FILE ...] [-i INSTRUCTIONS] [-c [ID]] [--detach] [-q] [--json]
    hi ls | show ID | output ID | log ID | files ID PATH | cancel ID
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from importlib.metadata import version
from pathlib import Path

import httpx

from . import daemon
from .api import DEFAULT_URL, Api, ApiError
from .harness import builtin, pack

LAST = daemon.HOME / "last-response"                 # what `hi run -c` continues


def err(*parts: object) -> None:
    print(*parts, file=sys.stderr, flush=True)


def show(data: object) -> None:
    print(json.dumps(data, indent=2))


def table(rows: list[list[str]]) -> None:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))] if rows else []
    for r in rows:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())


# ── server ──────────────────────────────────────────────────────────────────────────────────────
def server(api: Api, a: argparse.Namespace) -> int:
    if a.action == "start":
        pid = daemon.start(api)
        err(f"server running at {api.url} (pid {pid}); log: {daemon.LOG}")
    elif a.action == "stop":
        err("server stopped" if daemon.stop() else "no server was running")
    elif a.action == "status":
        pid = daemon.running()
        try:
            api.get("sandboxes")
            err(f"server answering at {api.url}" + (f" (pid {pid})" if pid else ""))
        except ApiError:
            err(f"no server answering at {api.url}")
            return 1
    else:
        print(daemon.tail(200))
    return 0


# ── the three resources ─────────────────────────────────────────────────────────────────────────
def provider(api: Api, a: argparse.Namespace) -> int:
    if a.action == "add":
        if a.key_env:
            key = os.environ.get(a.key_env) or sys.exit(f"hi: ${a.key_env} is not set")
        elif sys.stdin.isatty():
            key = getpass.getpass(f"key for {a.name}: ")
        else:
            key = sys.stdin.readline().strip()
        p = api.put("providers", a.name, {"name": a.name, "url": a.provider_url, "key": key})
        err(f"provider {p['name']} → {p['url']}")
    elif a.action == "ls":
        table([[p["name"], p["url"]] for p in api.get("providers")])
    return show_or_remove(api, a)


def sandbox(api: Api, a: argparse.Namespace) -> int:
    if a.action == "add":
        body = {"name": a.name, "dockerfile": Path(a.dockerfile).read_text(), "egress": a.egress}
        s = api.put("sandboxes", a.name, body)
        err(f"sandbox {s['name']}" + (f", may also reach {', '.join(s['egress'])}" if s["egress"] else ""))
    elif a.action == "ls":
        table([[s["name"], ", ".join(s["egress"])] for s in api.get("sandboxes")])
    return show_or_remove(api, a)


def harness(api: Api, a: argparse.Namespace) -> int:
    if a.action == "add":
        folders = builtin(a.folders) if a.builtin else [Path(f) for f in a.folders]
        if not folders:
            sys.exit("hi: name a harness folder, or use --builtin")
        for folder in folders:
            spec = pack(folder)
            h = api.put("harnesses", spec["name"], spec)
            err(f"harness {h['name']} (provider {h['provider']}, sandbox {h['sandbox']})")
    elif a.action == "ls":
        table([[h["name"], h["provider"], h["sandbox"]] for h in api.get("harnesses")])
    return show_or_remove(api, a)


def show_or_remove(api: Api, a: argparse.Namespace) -> int:
    if a.action == "show":
        show(api.get(a.path, a.name))
    elif a.action == "rm" and not api.delete(a.path, a.name):
        err(f"no {a.command} {a.name}")
        return 1
    return 0


# ── responses ───────────────────────────────────────────────────────────────────────────────────
def run(api: Api, a: argparse.Namespace) -> int:
    task = sys.stdin.read() if a.task == "-" else a.task
    files = [{"type": "input_file", "filename": Path(f).name, "file_data": Path(f).read_text()} for f in a.file]
    body: dict = {"model": a.harness, "input": [{"type": "input_text", "text": task}, *files] if files else task,
                  "instructions": a.instructions or ""}
    if a.continue_from == "last":
        if not LAST.exists():
            sys.exit("hi: no earlier response to continue")
        a.continue_from = LAST.read_text().strip()
    if a.continue_from:
        body["previous_response_id"] = a.continue_from
    record, rid = None, None
    try:
        for event, data in api.respond(body):
            if event == "response.created":
                rid = data["response"]["id"]
                LAST.parent.mkdir(parents=True, exist_ok=True)
                LAST.write_text(rid)
                if a.detach:
                    print(rid)
                    return 0
            elif event == "harness.output" and not (a.quiet or a.json):
                err(f"\033[2m{data['line']}\033[0m" if sys.stderr.isatty() else data["line"])
            elif event == "response.completed":
                record = data["response"]
    except KeyboardInterrupt:                        # Ctrl-C stops the run, not just the following
        if rid and api.cancel(rid):
            err(f"\ncancelled {rid}")
        return 130
    if record is None:
        err(f"hi: the stream ended before the run did; see `hi show {rid}`")
        return 1
    if a.json:
        show(record)
    else:
        answer = "".join(c["text"] for m in record["output"] for c in m.get("content", []))
        if answer:
            print(answer)
        err(summary(record))
    return 0 if record["status"] == "completed" else 1


def summary(r: dict) -> str:
    h = r["harness"]
    parts = [r["status"], f"{h['latency_s']}s" if h.get("latency_s") is not None else None,
             f"${h['cost_usd']:.4f}" if h.get("cost_usd") is not None else None,
             f"files: {', '.join(h['files'])}" if h.get("files") else None, r["id"]]
    line = " · ".join(p for p in parts if p)
    return line + (f"\n{r['error']['message']}" if r.get("error") else "")


def responses(api: Api, a: argparse.Namespace) -> int:
    records = api.responses()
    if a.json:
        show(records)
    else:
        table([[r["id"], r["status"], r["model"], str(r["harness"].get("latency_s") or "")] for r in records])
    return 0


def response(api: Api, a: argparse.Namespace) -> int:
    if a.command == "show":
        show(api.response(a.id))
    elif a.command == "cancel":
        if not api.cancel(a.id):
            err(f"{a.id} is not running")
            return 1
        err(f"cancelled {a.id}")
    else:
        data = {"output": api.output, "log": api.log}.get(a.command)
        sys.stdout.buffer.write(data(a.id) if data else api.file(a.id, a.path))
    return 0


# ── the command line ────────────────────────────────────────────────────────────────────────────
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hi", description="The command line for harness-interface.")
    p.add_argument("--url", help=f"the server (default: $HI_URL, else {DEFAULT_URL})")
    p.add_argument("--version", action="version", version=f"hi {version('harness-interface')}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("server", help="start, stop or check the server")
    s.add_argument("action", choices=["start", "stop", "status", "logs"])
    s.set_defaults(fn=server)

    for kind, path, fn in (("provider", "providers", provider), ("sandbox", "sandboxes", sandbox), ("harness", "harnesses", harness)):
        r = sub.add_parser(kind, help=f"add, list, show or remove {path}")
        acts = r.add_subparsers(dest="action", required=True)
        add = acts.add_parser("add")
        if kind == "provider":
            add.add_argument("name")
            add.add_argument("--url", dest="provider_url", required=True, help="where its model calls go")
            add.add_argument("--key-env", metavar="VAR", help="read the key from this variable (else it is prompted for)")
        elif kind == "sandbox":
            add.add_argument("name")
            add.add_argument("dockerfile")
            add.add_argument("--egress", nargs="*", default=[], metavar="HOST")
        else:
            add.add_argument("folders", nargs="*", metavar="FOLDER")
            add.add_argument("--builtin", action="store_true", help="the harnesses that ship with hi, by name; all if none named")
        acts.add_parser("ls")
        for act in ("show", "rm"):
            acts.add_parser(act).add_argument("name")
        r.set_defaults(fn=fn, path=path)

    r = sub.add_parser("run", help="send a task to a harness and stream its output")
    r.add_argument("harness", help="HARNESS or HARNESS/MODEL")
    r.add_argument("task", help="the task; - reads it from stdin")
    r.add_argument("-f", "--file", action="append", default=[], help="a file to put in the workspace")
    r.add_argument("-i", "--instructions")
    r.add_argument("-c", "--continue", dest="continue_from", nargs="?", const="last", metavar="ID",
                   help="continue a conversation: the last response, or the one named")
    r.add_argument("--detach", action="store_true", help="print the response id and leave it running")
    r.add_argument("-q", "--quiet", action="store_true", help="do not show the harness's output while it runs")
    r.add_argument("--json", action="store_true", help="print the finished record")
    r.set_defaults(fn=run)

    ls = sub.add_parser("ls", help="list responses")
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(fn=responses)
    for cmd, what in (("show", "a response's record"), ("output", "a response's stdout"),
                      ("log", "a response's stderr"), ("cancel", "stop a running response")):
        c = sub.add_parser(cmd, help=what)
        c.add_argument("id")
        c.set_defaults(fn=response)
    f = sub.add_parser("files", help="a file from a response's workspace")
    f.add_argument("id")
    f.add_argument("path")
    f.set_defaults(fn=response)
    return p


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    api = Api(a.url)
    try:
        return a.fn(api, a)
    except (ApiError, RuntimeError, ValueError, OSError) as e:
        err(f"hi: {e}")
        return 1
    except httpx.HTTPError as e:                     # the server went away mid-request
        err(f"hi: lost the server at {api.url}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
