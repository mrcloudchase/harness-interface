"""Run a harness folder from Python, with no server: the library's Turn, in the default sandbox on
Docker, or on this machine with --local.

    python examples/library/run_a_harness.py harnesses/claude-code "Write a haiku about a hermit crab." \\
        --provider-url https://api.anthropic.com --key-env ANTHROPIC_API_KEY

The harness's own output streams as it works; then the answer, and a summary of the turn. Continue
the conversation by running it again with the same --workspace and --session.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from harness_interface import Docker, DockerRuntime, Harness, LocalRuntime, Provider, Request, Turn
from harness_interface.resources import DEFAULT_SANDBOX


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("folder", type=Path, help="a harness folder: harness.json and its scripts")
    p.add_argument("task")
    p.add_argument("--provider-url", required=True)
    p.add_argument("--key-env", required=True, help="the environment variable that holds the provider's key")
    p.add_argument("--workspace", type=Path, default=Path("workspace"))
    p.add_argument("--session", default="", help="the session_id an earlier turn reported, to continue it")
    p.add_argument("--local", action="store_true", help="run on this machine, with no sandbox")
    args = p.parse_args()

    folder = args.folder.resolve()
    harness = Harness.from_folder(folder)
    provider = Provider(harness.provider, args.provider_url, os.environ[args.key_env])
    if args.local:
        runtime = LocalRuntime()
    else:
        engine = Docker(Path.home() / ".harness-interface" / "data" / "logs")
        runtime = DockerRuntime(engine, DEFAULT_SANDBOX, egress=[provider.host], mounts=[folder])

    turn = await Turn.start(runtime, harness, provider, Request(args.task, session_id=args.session),
                            args.workspace.resolve(), folder)
    async for event in turn.events():                # all of it to stderr: stdout is kept for the answer
        sys.stderr.buffer.write(event.data)
        sys.stderr.flush()
    result = await turn.result()
    print(result.answer)
    print(f"{result.status} · exit {result.exit_code} · session {result.session_id or '-'} · "
          f"changed {', '.join(result.files) or 'nothing'}", file=sys.stderr)
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
