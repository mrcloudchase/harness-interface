"""`hi serve`: the API server. `hi pack`: a harness folder as the JSON its PUT takes."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .models import Harness


def serve(args) -> None:
    import uvicorn
    from .app import build, create_app
    from .config import Settings
    settings = Settings(runtime=args.runtime or os.environ.get("HI_RUNTIME", "docker"))
    uvicorn.run(create_app(build(settings)), host=args.host, port=args.port, log_level="info")


def packed(folder: Path) -> Harness:
    """harness.yaml plus every other file in the folder, as one resource."""
    import yaml
    spec = yaml.safe_load((folder / "harness.yaml").read_text())
    spec["scripts"] = {p.name: p.read_text() for p in sorted(folder.iterdir())
                       if p.is_file() and p.name != "harness.yaml"}
    return Harness(**spec)


def pack(args) -> None:
    print(packed(Path(args.folder)).model_dump_json(indent=2))


def main() -> None:
    p = argparse.ArgumentParser(prog="hi")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the API server")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    s.add_argument("--runtime", choices=["docker", "local"], help="where harnesses run (default: docker, or $HI_RUNTIME)")
    s.set_defaults(fn=serve)
    k = sub.add_parser("pack", help="print a harness folder as the JSON for PUT /harnesses/{name}")
    k.add_argument("folder"); k.set_defaults(fn=pack)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
