"""Layer 3: the contract, written once. Nothing else knows what a harness is given or gives back.

`prepare` readies the workspace for one response and says what to run:
- the folder's `workspace/` (work artifacts) is copied in when the session starts, and only then;
- the request's files (text or bytes) are written into the workspace, never into its internal paths;
- the folder's `home/` (config artifacts) is copied into `.home` every response, so the folder always
  wins for what it ships; then every `files` entry is rendered, and an empty render deletes its file;
- a snapshot marks where the response starts, and the reported artifacts' state is noted;
- the Spec is `bash run.sh` in the workspace, its input line 1, `{"task", "resume"}`, its input kept
  open, and its environment exactly HI_WORKSPACE, HOME, HI_HARNESS_DIR, HI_OUTPUT, HI_MODEL, PATH and,
  with a provider, HI_PROVIDER_URL, HI_PROVIDER_API and HI_PROVIDER_KEY_FILE.

`collect` turns what the response left into a Result. The status is the harness's own, from
HI_OUTPUT, never the exit code; one cut off while it still said `running` (or said nothing) is
`stopped` if a stop was asked for and it had a resume, else `fail`. Every key of HI_OUTPUT is kept,
and `usage` is as reported. With it come the work's changes (outside `.home/`) and the reported
artifacts under `.home/` that the response added, changed or deleted.
"""
from __future__ import annotations

import json
import os
import posixpath
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..errors import Invalid
from ..execution import Outcome, Spec
from ..workspace import HOME, Workspace, internal
from .folder import HarnessFolder

OUTPUT = "output.json"
ENDED = ("ok", "fail", "stopped")


def session_token(api: str) -> str:
    """A session's stand-in for its key under the gateway, shaped like a real one for CLIs that check."""
    return ("sk-ant-api03-hi-" if api == "anthropic-messages" else "sk-hi-") + secrets.token_hex(24)


@dataclass(frozen=True)
class Request:
    """What one response asks of a harness."""
    task: str
    resume: str | None = None                        # the CLI's conversation to continue, as it reported it
    instructions: str = ""                           # rendered into `files`; nowhere else
    model: str = ""
    files: Mapping[str, str | bytes] = field(default_factory=dict)   # workspace path -> content

    def __post_init__(self) -> None:
        if not isinstance(self.task, str):
            raise Invalid("a task is text")
        if self.resume is not None and (not isinstance(self.resume, str) or not self.resume):
            raise Invalid("resume is the text a harness reported, or nothing")
        if not isinstance(self.instructions, str) or not isinstance(self.model, str):
            raise Invalid("instructions and model are text")
        files = dict(self.files)
        for rel, content in files.items():
            if not isinstance(rel, str) or not isinstance(content, (str, bytes)):
                raise Invalid("request files map paths to text or bytes")
            if internal(posixpath.normpath(rel)):
                raise Invalid(f"a request file can't be written into an internal path: {rel!r}")
        object.__setattr__(self, "files", MappingProxyType(files))


@dataclass(frozen=True)
class Prepared:
    """A response, ready to run: its Spec, the snapshot it starts from, and the reported artifacts' state."""
    spec: Spec
    base: str
    home: Mapping[str, str]
    output: Path


@dataclass(frozen=True)
class Result:
    """What one response gave back."""
    status: str                                      # ok | fail | stopped
    answer: str
    resume: str | None
    usage: Mapping[str, Any]
    cost_usd: float | None
    steers: int                                      # the steers the harness took
    steers_sent: int                                 # the steers sent: the rest arrived too late
    output: Mapping[str, Any]                        # all of HI_OUTPUT, its extra keys too
    outcome: Outcome                                 # how its process ended
    stop: str | None                                 # why it was asked to stop: "requested", "timeout"
    base: str                                        # the snapshot before it
    commit: str                                      # the snapshot after it
    changes: Mapping[str, bytes | None]              # workspace path -> new content, None if deleted
    home: Mapping[str, bytes | None]                 # reported artifact, by path under $HOME -> content, None if deleted

    @property
    def undelivered(self) -> int:
        return max(0, self.steers_sent - self.steers)


def prepare(folder: HarnessFolder, workspace: Workspace, request: Request, *, rundir: Path, tools: Path,
            path: str, provider_url: str | None = None, provider_api: str | None = None,
            key_file: Path | None = None, new_session: bool = False) -> Prepared:
    """Ready the workspace and the run directory for one response, and say what to run. `path` is what
    follows the tools on PATH; the provider's URL and key file are where the run reaches them."""
    workspace.init()
    home = workspace.path / HOME
    if home.is_symlink() or (home.exists() and not home.is_dir()):
        raise Invalid(f"the workspace's {HOME} is not a directory")
    home.mkdir(exist_ok=True)
    if new_session and folder.workspace:
        copy_in(folder.workspace, workspace, "")
    for rel, content in request.files.items():
        workspace.write(rel, content)
    if folder.home:
        copy_in(folder.home, workspace, f"{HOME}/")
    for rel, template in folder.files.items():
        rendered = template.replace("{instructions}", request.instructions)
        if rendered.strip():
            workspace.write(rel, rendered)
        else:
            workspace.delete(rel)                    # else a response with no instructions keeps the last ones
    rundir.mkdir(parents=True, exist_ok=True)
    output = rundir / OUTPUT
    for stale in (output, output.with_name(f"{OUTPUT}.tmp")):
        stale.unlink(missing_ok=True)
    env = {"HI_WORKSPACE": str(workspace.path), "HOME": str(home), "HI_HARNESS_DIR": str(folder.path),
           "HI_OUTPUT": str(output), "HI_MODEL": request.model, "PATH": f"{tools}/bin:{path}"}
    if provider_url:
        env.update(HI_PROVIDER_URL=provider_url, HI_PROVIDER_API=provider_api, HI_PROVIDER_KEY_FILE=str(key_file))
    line = json.dumps({"task": request.task, "resume": request.resume}, separators=(",", ":")) + "\n"
    spec = Spec(("bash", str(folder.path / "run.sh")), input=line.encode(), env=env, workspace=workspace.path,
                interactive=True)
    return Prepared(spec, workspace.snapshot("before the response"), workspace.home_files(folder.report), output)


def copy_in(source: Path, workspace: Workspace, prefix: str) -> None:
    """Every file under `source` into the workspace under `prefix`, readable and writable by its owner."""
    for p in sorted(source.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = prefix + p.relative_to(source).as_posix()
            workspace.write(rel, p.read_bytes())
            os.chmod(workspace.resolve(rel), (p.stat().st_mode & 0o755) | 0o644)


def read_output(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def number(value: Any, kind: type | tuple[type, ...] = (int, float)) -> bool:
    return isinstance(value, kind) and not isinstance(value, bool)


def reported(folder: HarnessFolder, workspace: Workspace, prepared: Prepared) -> dict[str, bytes | None]:
    """The reported artifacts the response has added, changed (path -> content) or deleted (None) so far."""
    after = workspace.home_files(folder.report)
    return {**{p: workspace.read_home(p) for p, digest in after.items() if prepared.home.get(p) != digest},
            **{p: None for p in prepared.home if p not in after}}


def collect(folder: HarnessFolder, workspace: Workspace, prepared: Prepared, *, outcome: Outcome,
            stop: str | None = None, steers_sent: int = 0) -> Result:
    """What the response gave back, once its process has ended."""
    out = read_output(prepared.output)
    resume = out.get("resume") if isinstance(out.get("resume"), str) and out.get("resume") else None
    status = out.get("status")
    if status not in ENDED:                          # cut off while running, or it never said
        status = "stopped" if stop and resume else "fail"
    answer = out.get("answer") if isinstance(out.get("answer"), str) else ""
    if not answer and outcome.kind == "failed":
        answer = outcome.reason
    cost, steers = out.get("cost_usd"), out.get("steers")
    commit = workspace.snapshot("after the response")
    changed, deleted = workspace.changes(prepared.base, commit)
    changes = {**{p: workspace.read(p, commit) for p in changed}, **{p: None for p in deleted}}
    home = reported(folder, workspace, prepared)
    return Result(status=status, answer=answer, resume=resume,
                  usage=MappingProxyType(out["usage"] if isinstance(out.get("usage"), dict) else {}),
                  cost_usd=cost if number(cost) else None, steers=steers if number(steers, int) else 0,
                  steers_sent=steers_sent, output=MappingProxyType(out), outcome=outcome, stop=stop,
                  base=prepared.base, commit=commit, changes=MappingProxyType(changes), home=MappingProxyType(home))
