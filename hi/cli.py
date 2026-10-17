"""`hi serve`: start the API server. Everything else is done through the API."""
from __future__ import annotations

import argparse
import os


def serve(args) -> None:
    import uvicorn
    from .app import build, create_app
    from .config import Settings
    settings = Settings(runtime=args.runtime or os.environ.get("HI_RUNTIME", "docker"))
    uvicorn.run(create_app(build(settings)), host=args.host, port=args.port, log_level="info")


def main() -> None:
    p = argparse.ArgumentParser(prog="hi")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the API server")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8000)
    s.add_argument("--runtime", choices=["docker", "local"], help="where harnesses run (default: docker, or $HI_RUNTIME)")
    s.set_defaults(fn=serve)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
