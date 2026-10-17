"""`hi serve`: the API server. `hi pack`: a harness folder or sandbox file as the JSON its PUT
takes. `hi apply`: PUT harness folders and sandbox files to a running server."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from pydantic import BaseModel

from .models import Harness, Sandbox


def serve(args) -> None:
    import uvicorn
    from .app import build, create_app
    from .config import Settings
    settings = Settings(runtime=args.runtime or os.environ.get("HI_RUNTIME", "docker"))
    uvicorn.run(create_app(build(settings)), host=args.host, port=args.port, log_level="info")


def packed(path: Path) -> Harness | Sandbox:
    """A folder is a harness: its harness.yaml plus every other file in it as a script.
    A .yaml file is a sandbox."""
    import yaml
    if path.is_dir():
        spec = yaml.safe_load((path / "harness.yaml").read_text())
        spec["scripts"] = {p.name: p.read_text() for p in sorted(path.iterdir())
                           if p.is_file() and p.name != "harness.yaml"}
        return Harness(**spec)
    return Sandbox(**yaml.safe_load(path.read_text()))


def pack(args) -> None:
    print(packed(Path(args.path)).model_dump_json(indent=2))


def apply(args) -> None:
    """Sandboxes first, so the harnesses that name them find them."""
    paths = [Path(p) for p in args.paths if Path(p).is_dir() or Path(p).suffix in (".yaml", ".yml")]   # skips READMEs
    resources: list[BaseModel] = sorted((packed(p) for p in paths), key=lambda r: isinstance(r, Harness))
    failed = False
    for r in resources:
        kind = "harnesses" if isinstance(r, Harness) else "sandboxes"
        req = urllib.request.Request(f"{args.url.rstrip('/')}/{kind}/{r.name}", data=r.model_dump_json().encode(),
                                     method="PUT", headers={"content-type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                print(f"{kind[:-2]} {r.name}: {resp.status}")
        except urllib.error.HTTPError as e:
            failed = True
            print(f"{kind[:-2]} {r.name}: {e.code} {e.read().decode(errors='replace')[:200]}", file=sys.stderr)
    sys.exit(1 if failed else 0)


def main() -> None:
    p = argparse.ArgumentParser(prog="hi")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the API server")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    s.add_argument("--runtime", choices=["docker", "local"], help="where harnesses run (default: docker, or $HI_RUNTIME)")
    s.set_defaults(fn=serve)
    k = sub.add_parser("pack", help="print a harness folder or sandbox .yaml as the JSON its PUT takes")
    k.add_argument("path"); k.set_defaults(fn=pack)
    a = sub.add_parser("apply", help="PUT harness folders and sandbox .yaml files to a running server")
    a.add_argument("paths", nargs="+"); a.add_argument("--url", default=os.environ.get("HI_URL", "http://127.0.0.1:8000"))
    a.set_defaults(fn=apply)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
