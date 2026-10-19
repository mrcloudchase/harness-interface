"""Layer 3: the harness contract. What harness.json means, what a harness is given, and what it
gives back. This is the one place the contract is written down in code.

A harness is given:
- its request on stdin, and in the file at HI_REQUEST;
- HI_TASK, HI_MODEL, HI_SESSION_ID, HI_PROVIDER_URL, HI_PROVIDER_KEY, HI_WORKSPACE, HI_HARNESS_DIR
  and HI_OUTPUT, plus its own `run.env`, templated;
- the request's files and its own templated `files`, in the workspace, which is its working directory.

It gives back whatever it prints, whatever it changes in the workspace, and, if it likes, a JSON
object in the file at HI_OUTPUT: `answer`, `status` ("ok" or "fail"), `session_id`, `usage`,
`cost_usd`. Every key is optional. The contract is closed: nothing is added to it, and nothing it
gives a harness is taken away or renamed. Of any harness, now or later, it assumes only that it
takes input and returns output.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, Mapping

from ..errors import Invalid
from ..execution import Outcome, Spec
from ..runtimes.egress import normalize
from ..workspace import Workspace
from .template import render, render_all

OUTPUT_FILE = ".hi/output.json"
REQUEST_FILE = ".hi/request.json"


@dataclass(frozen=True)
class Provider:
    """Where a harness's model calls go, and the key that unlocks them. The harness decides which
    of its CLI's settings get them."""
    name: str
    url: str
    key: str = field(repr=False)                     # never in a repr, a log or a traceback

    @property
    def host(self) -> str:
        """host:port, by the rule the egress door reads its allowlist with."""
        return normalize(self.url)


@dataclass(frozen=True)
class Run:
    """How a harness is run."""
    argv: tuple[str, ...] = ("bash", "{harness_dir}/run.sh")
    env: dict[str, str] = field(default_factory=dict)          # templated, beside the contract's variables
    stdout: str = "application/x-ndjson"                       # what it prints, as a content type
    timeout_s: int = 900

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", tuple(self.argv))
        if not self.argv:
            raise Invalid("run.argv must not be empty")
        if self.timeout_s <= 0:
            raise Invalid("run.timeout_s must be positive")


@dataclass(frozen=True)
class Harness:
    """Everything needed to run one CLI: its scripts, its command, the files it wants in the
    workspace, and by name the provider it calls and the sandbox it runs in."""
    name: str
    provider: str
    sandbox: str = "default"
    description: str = ""
    files: dict[str, str] = field(default_factory=dict)        # path -> content, both templated
    run: Run = field(default_factory=Run)
    scripts: dict[str, str] = field(default_factory=dict)      # filename -> content, in its scripts directory

    def __post_init__(self) -> None:
        if isinstance(self.run, dict):
            object.__setattr__(self, "run", Run(**self.run))
        bad = [n for n in self.scripts if not n or "/" in n or n.startswith(".")]
        if bad:
            raise Invalid(f"a script name must be a plain filename: {bad[0]!r}")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Harness:
        known = {f.name for f in fields(cls)}
        if unknown := set(data) - known:
            raise Invalid(f"unknown harness fields: {', '.join(sorted(unknown))}")
        try:
            return cls(**data)
        except TypeError as e:                       # a field of the wrong shape
            raise Invalid(str(e)) from None

    @classmethod
    def from_folder(cls, folder: Path) -> Harness:
        """A harness folder: harness.json, and every other file in it as a script."""
        spec = Path(folder) / "harness.json"
        if not spec.is_file():
            raise Invalid(f"{folder} has no harness.json")
        data = json.loads(spec.read_text())
        data["scripts"] = {p.name: p.read_text() for p in sorted(Path(folder).iterdir())
                           if p.is_file() and p.name != "harness.json"}
        return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_scripts(self, directory: Path) -> None:
        """Its scripts as files, replacing whatever was there."""
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.iterdir():
            old.unlink()
        for name, content in self.scripts.items():
            (directory / name).write_text(content)


@dataclass(frozen=True)
class Request:
    """One turn's request, as the harness receives it."""
    task: str
    instructions: str = ""
    model: str = ""                                  # passed through to the harness's CLI
    files: dict[str, str] = field(default_factory=dict)        # path -> text, written into the workspace
    session_id: str = ""                             # what the previous turn reported, to resume
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise Invalid("the request has no task")


Status = Literal["ok", "fail", "timeout", "cancelled"]


@dataclass(frozen=True)
class Result:
    """What a turn came to: how it ended, what the harness reported, and what it changed."""
    status: Status
    exit_code: int | None = None
    answer: str = ""
    session_id: str = ""                             # as reported; empty if it reported none
    usage: dict[str, Any] | None = None
    cost_usd: float | None = None
    error: str = ""                                  # why it never ran, if it didn't
    files: tuple[str, ...] = ()                      # added or modified
    deleted: tuple[str, ...] = ()
    base: str = ""                                   # the workspace's snapshot before the turn
    commit: str = ""                                 # and after it


def prepare(harness: Harness, provider: Provider, request: Request, workspace: Workspace, scripts: Path) -> Spec:
    """Write what the harness is given into its workspace, and the Spec that runs it."""
    given = {"task": request.task, "instructions": request.instructions, "model": request.model,
             "session_id": request.session_id}
    ctx = {**given, "workspace": str(workspace.path), "harness_dir": str(scripts),
           "provider_url": provider.url, "provider_key": provider.key}
    for rel, content in request.files.items():
        workspace.write(rel, content)
    for rel, content in harness.files.items():
        workspace.write(render(rel, ctx), render(content, ctx))
    body = json.dumps({**given, "files": sorted(request.files), "metadata": request.metadata}, indent=2)
    workspace.write(REQUEST_FILE, body)
    (workspace.path / OUTPUT_FILE).unlink(missing_ok=True)     # only this turn's report counts
    env = {
        **render_all(harness.run.env, ctx),
        "HI_TASK": request.task,
        "HI_MODEL": request.model,
        "HI_SESSION_ID": request.session_id,
        "HI_REQUEST": str(workspace.path / REQUEST_FILE),
        "HI_OUTPUT": str(workspace.path / OUTPUT_FILE),
        "HI_WORKSPACE": str(workspace.path),
        "HI_HARNESS_DIR": str(scripts),
        "HI_PROVIDER_URL": provider.url,
        "HI_PROVIDER_KEY": provider.key,
    }
    return Spec(render_all(harness.run.argv, ctx), input=body.encode(), env=env, workspace=workspace.path,
                timeout_s=harness.run.timeout_s)


def collect(outcome: Outcome, workspace: Workspace) -> Result:
    """What the harness reported, under how it ended. A timeout or a cancel decides first, then
    the status it reported, then its exit code."""
    out = _reported(workspace)
    if outcome.kind == "failed":
        return Result("fail", error=outcome.reason)
    cost = out.get("cost_usd")
    answer = out.get("answer")
    return Result(
        status=_status(outcome, out.get("status")),
        exit_code=outcome.code,
        answer=answer if isinstance(answer, str) and answer.strip() else "",
        session_id=str(out["session_id"]) if out.get("session_id") else "",
        usage=out["usage"] if isinstance(out.get("usage"), dict) else None,
        cost_usd=float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
    )


def _status(outcome: Outcome, reported: Any) -> Status:
    if outcome.kind == "timed_out":
        return "timeout"
    if outcome.kind == "cancelled":
        return "cancelled"
    if reported in ("ok", "fail"):
        return reported
    return "ok" if outcome.ok else "fail"


def _reported(workspace: Workspace) -> dict[str, Any]:
    p = workspace.path / OUTPUT_FILE
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
