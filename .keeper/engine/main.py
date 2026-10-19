"""Keeper's entry point, run by the workflows from the repository's root.

    python .keeper/engine/main.py route            the event → tasks, as a job output
    python .keeper/engine/main.py run TASK [ITEM]  one task
    python .keeper/engine/main.py replay           Evolve's check: replay accepted tasks

Configuration comes from keeper.toml; credentials from the environment the workflow gives this
step and no other: GITHUB_TOKEN, and KEEPER_SECRETS (the job's secrets as JSON) for the providers.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import tasks
from config import Config
from context import Context
from github import GitHub
from governor import Governor
from router import route
from runtime import Runtime
from workspace import Workspace


def secrets() -> dict[str, str]:
    return {**os.environ, **json.loads(os.environ.get("KEEPER_SECRETS") or "{}")}


def context(root: Path, agents: bool) -> Context:
    config = Config.load(root)
    env = secrets()
    gh = GitHub(env["GITHUB_REPOSITORY"], env["GITHUB_TOKEN"])
    runtime = None
    if agents:
        runtime = Runtime(root, env.get("HI_URL", "http://127.0.0.1:8000"),
                          sandboxed=env.get("GITHUB_ACTIONS") == "true")
        for name, p in config.providers.items():
            if env.get(p["key"]):
                runtime.provider(name, p["url"], env[p["key"]])
    live_keys = {k: env[k] for k in config.live.get("secrets", []) if env.get(k)}
    workspace = Workspace(root, token=env["GITHUB_TOKEN"], secrets=live_keys)
    return Context(config, gh, workspace, Governor(config, gh, env.get("KEEPER_ENABLED") == "true"), runtime)


def main(argv: list[str]) -> int:
    root = Path.cwd()
    if argv[:1] == ["route"]:
        config = Config.load(root)
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        found = [{"task": t, "item": i, "kind": tasks.kind(config, t)} for t, i in route(config, os.environ["GITHUB_EVENT_NAME"], payload)]
        print(json.dumps(found))
        with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as out:
            out.write(f"tasks={json.dumps(found)}\n")
        return 0
    if argv[:1] == ["run"] and len(argv) >= 2:
        config = Config.load(root)
        ctx = context(root, tasks.kind(config, argv[1]) == "agent")
        print(f"{argv[1]} {argv[2] if len(argv) > 2 else ''}: {tasks.run(ctx, argv[1], argv[2] if len(argv) > 2 else '')}")
        return 0
    if argv[:1] == ["replay"]:
        return 0 if tasks.replay(context(root, agents=True)) else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
