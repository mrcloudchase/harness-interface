"""The process contract, and nothing else.

Prepare: write the input files and the harness's templated files into the workspace, write
request.json, build the variables the harness is promised. Templates in the harness's argv, env
and files take {task} {instructions} {model} {session_id} {workspace} {harness_dir}
{provider_url} {provider_key}. Read back what the harness wrote to
HI_OUTPUT when it is done. Where the workspace and the scripts appear from inside the sandbox is
the sandbox's business, so it is passed in as `Mounts`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .models import Harness, Provider, ResponseRequest
from .template import render, render_obj
from .workspace import Workspace

OUTPUT_FILE = ".hi/output.json"
REQUEST_FILE = ".hi/request.json"


@dataclass(frozen=True)
class Mounts:
    workspace: str                                   # the workspace's path as the harness sees it
    harness: str                                     # the scripts' path as the harness sees it


@dataclass(frozen=True)
class Prepared:
    argv: list[str]
    env: dict[str, str]                              # what the harness is given, on top of nothing
    stdin: bytes
    timeout_s: int


class Runner:
    @staticmethod
    def prepare(harness: Harness, provider: Provider, req: ResponseRequest, session_id: str | None,
                ws: Workspace, mounts: Mounts) -> Prepared:
        ctx = {"task": req.task, "instructions": req.instructions, "model": req.model_name,
               "session_id": session_id or "", "workspace": mounts.workspace, "harness_dir": mounts.harness,
               "provider_url": provider.url, "provider_key": provider.key}
        for rel, content in req.files.items():
            ws.write(rel, content)
        for rel, content in harness.files.items():
            ws.write(render(rel, ctx), render(content, ctx))
        body = json.dumps({"task": req.task, "instructions": req.instructions, "model": req.model_name,
                           "files": sorted(req.files), "session_id": session_id or "", "metadata": req.metadata}, indent=2)
        ws.write(REQUEST_FILE, body)
        env = {
            **render_obj(harness.run.env, ctx),
            "HI_TASK": req.task,
            "HI_MODEL": req.model_name,
            "HI_SESSION_ID": session_id or "",
            "HI_REQUEST": f"{mounts.workspace}/{REQUEST_FILE}",
            "HI_OUTPUT": f"{mounts.workspace}/{OUTPUT_FILE}",
            "HI_WORKSPACE": mounts.workspace,
            "HI_HARNESS_DIR": mounts.harness,
            "HI_PROVIDER_URL": provider.url,
            "HI_PROVIDER_KEY": provider.key,
        }
        return Prepared(argv=render_obj(harness.run.argv, ctx), env=env, stdin=body.encode(),
                        timeout_s=harness.run.timeout_s)


def read_output(ws: Workspace) -> dict:
    p = ws.path / OUTPUT_FILE
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}
