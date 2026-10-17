"""`hi`: serve the API, and a small client for it (apply resources, store secrets, run tasks)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

from .registry import load_spec

DEFAULT_URL = os.environ.get("HI_URL", "http://127.0.0.1:8000")


def serve(args) -> None:
    import uvicorn
    from .app import create_app
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


def apply(args) -> None:
    with httpx.Client(base_url=args.url, timeout=120) as c:
        for f in args.files:
            spec = load_spec(Path(f))
            path = f"/harnesses/{spec.name}" if spec.kind == "Harness" else "/route"
            r = c.put(path, json=spec.model_dump(mode="json"))
            r.raise_for_status()
            d = r.json()
            tag = f"v{d['version']}" + (f" check_ok={d['check_ok']}" if spec.kind == "Harness" else "")
            print(f"applied {spec.kind} {getattr(spec, 'name', 'route')} {tag}")


def secret(args) -> None:
    value = args.value or os.environ.get(args.name) or sys.stdin.read()
    with httpx.Client(base_url=args.url, timeout=30) as c:
        c.put(f"/secrets/{args.name}", content=value.strip()).raise_for_status()
    print(f"stored {args.name}")


def run(args) -> None:
    """Stream what comes back: one harness's own output, or, for fan-out, NDJSON lines tagged by
    harness. The record is printed to stderr when it ends."""
    body = {"task": args.task, "instructions": args.instructions or "", "stream": True, "mode": args.mode,
            "harness": args.harness, "session": args.session, "model": args.model,
            "files": [{"name": Path(p).name, "content": Path(p).read_text()} for p in args.file]}
    with httpx.Client(base_url=args.url, timeout=None) as c:
        with c.stream("POST", "/runs", json=body) as r:
            if r.status_code >= 400:
                print(r.read().decode(), file=sys.stderr)
                sys.exit(1)
            contest = r.headers.get("x-contest-id")
            print(f"contest={contest}" if contest else
                  f"run={r.headers['x-run-id']} session={r.headers['x-session-id']} harness={r.headers['x-harness']}",
                  file=sys.stderr)
            for chunk in r.iter_bytes():
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
        if contest:
            info = c.get(f"/contests/{contest}").json()
            keep = ("id", "status", "winner", "session", "runs", "note")
        else:
            info = c.get(f"/runs/{r.headers['x-run-id']}").json()
            keep = ("id", "status", "latency_s", "usage", "files", "verdict")
        print(json.dumps({k: info[k] for k in keep}, indent=2), file=sys.stderr)


def verdict(args) -> None:
    with httpx.Client(base_url=args.url, timeout=30) as c:
        r = c.patch(f"/runs/{args.run_id}", json={"success": args.outcome == "pass", "note": args.note or ""})
        r.raise_for_status()
        print(json.dumps(r.json()["verdict"], indent=2))


def show(args) -> None:
    with httpx.Client(base_url=args.url, timeout=30) as c:
        r = c.get(args.path)
        print(json.dumps(r.json(), indent=2))


def main() -> None:
    p = argparse.ArgumentParser(prog="hi")
    p.add_argument("--url", default=DEFAULT_URL)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=serve)
    a = sub.add_parser("apply", help="register Harness/Route YAML files"); a.add_argument("files", nargs="+"); a.set_defaults(fn=apply)
    k = sub.add_parser("secret", help="store a secret (value from arg, env, or stdin)")
    k.add_argument("name"); k.add_argument("value", nargs="?"); k.set_defaults(fn=secret)
    r = sub.add_parser("run", help="send a task: to every harness (fan-out), to the route's pick, or to one by name")
    r.add_argument("task"); r.add_argument("--mode", choices=["fanout", "route", "named"], help="default: named with --harness/--session, else fanout")
    r.add_argument("--harness"); r.add_argument("--session"); r.add_argument("--model")
    r.add_argument("--instructions"); r.add_argument("--file", action="append", default=[])
    r.set_defaults(fn=run)
    v = sub.add_parser("verdict", help="record a person's verdict on a run")
    v.add_argument("run_id"); v.add_argument("outcome", choices=["pass", "fail"]); v.add_argument("--note"); v.set_defaults(fn=verdict)
    g = sub.add_parser("get", help="GET any path, e.g. /runs, /runs/<id>, /contests, /cards"); g.add_argument("path"); g.set_defaults(fn=show)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
