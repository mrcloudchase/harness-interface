"""Layer 3: a harness folder, loaded only when it is exactly what contract 1 says.

A folder is `harness.json` (a closed schema: an unknown or missing field is an error, and every
problem is named at once), `install.sh`, `run.sh`, `adapter.py`, `hi_adapter.py`, and optionally
`home/` (config artifacts), `workspace/` (work artifacts) and `image.Dockerfile` (`FROM hi-base`, for
OS packages). Its default provider's URL follows the rule every provider's does (`check_provider_url`):
the base URL the shape's official SDK takes, so no adapter ever guesses at one.

`hi_adapter.py` is the plumbing every adapter shares, copied byte-identical into every folder rather
than injected, so a folder runs on its own. The canonical copy ships with the server as
`harness_interface/harness/hi_adapter.py` (package data, so an installed server can check any folder
it is given); `harnesses/template/hi_adapter.py` is a copy of it like any other, and a folder whose
copy differs is refused. To change it, change the canonical copy and every folder's in one commit.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..errors import Invalid
from ..runtimes.door import APIS
from ..workspace import internal

CONTRACT = 1
CANONICAL_ADAPTER = Path(__file__).with_name("hi_adapter.py")
REQUIRED_FILES = ("harness.json", "install.sh", "run.sh", "adapter.py", "hi_adapter.py")
INTERRUPTS = ("steered", "continued", "responded")
CREDENTIALS = ("gateway", "file")
BASE_FROM = "FROM hi-base"                           # an image.Dockerfile's first instruction, naming the base image
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
HOST = re.compile(r"[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?")
CONTENT_TYPE = re.compile(r"[\w.+-]+/[\w.+-]+")
VERSION = re.compile(r"v\d+\w*")                     # a version segment: v1, v1beta, v4


def check_provider_url(url: str, api: str) -> None:
    """Refuse a provider URL that isn't the base URL the shape's official SDK takes: `https://`, no
    credentials, query or fragment; `anthropic-messages` without a version path (the SDK adds
    `/v1/messages`), `openai-*` with one (`/v1`; the SDK adds `/responses` or `/chat/completions`)."""
    if api not in APIS:
        raise Invalid(f"unknown API shape {api!r}: one of {', '.join(APIS)}")
    u = urlsplit(url) if isinstance(url, str) else None
    if not u or u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise Invalid(f"a provider URL is https://host[/path], with no credentials, query or fragment: {url!r}")
    segments = [s for s in u.path.split("/") if s]
    if api == "anthropic-messages" and segments and VERSION.fullmatch(segments[-1]):
        raise Invalid(f"an anthropic-messages URL has no version path (the SDK adds /v1/messages): {url!r}")
    if api != "anthropic-messages" and not any(VERSION.fullmatch(s) for s in segments):
        raise Invalid(f"an {api} URL ends with its version path, such as /v1: {url!r}")


@dataclass(frozen=True)
class Endpoint:
    url: str
    api: str


@dataclass(frozen=True)
class InstallPlan:
    egress: tuple[str, ...]
    timeout_s: float


@dataclass(frozen=True)
class RunPlan:
    interrupt: str
    stdout: str
    timeout_s: float
    stop_timeout_s: float
    credential: str = "gateway"
    egress: tuple[str, ...] = ()


@dataclass(frozen=True)
class HarnessFolder:
    path: Path
    contract: int
    name: str
    description: str
    provider: Endpoint
    apis: tuple[str, ...]
    install: InstallPlan
    files: Mapping[str, str]
    run: RunPlan
    report: tuple[str, ...]

    @classmethod
    def load(cls, path: Path) -> HarnessFolder:
        """The folder at `path`, or Invalid naming everything wrong with it."""
        path = Path(path).resolve()
        problems = [f"missing {name}" for name in REQUIRED_FILES if not (path / name).is_file()]
        spec: Any = None
        if (path / "harness.json").is_file():
            try:
                spec = json.loads((path / "harness.json").read_text())
            except (ValueError, UnicodeDecodeError) as e:
                problems.append(f"harness.json is not JSON: {e}")
        if spec is not None and not isinstance(spec, dict):
            problems.append("harness.json must be an object")
        if isinstance(spec, dict):
            problems += schema(spec)
        problems += folder_problems(path)
        if problems:
            raise Invalid(f"harness folder {path}: " + "; ".join(problems))
        run = spec["run"]
        return cls(path=path, contract=spec["contract"], name=spec["name"], description=spec["description"],
                   provider=Endpoint(**spec["provider"]), apis=tuple(spec["apis"]),
                   install=InstallPlan(tuple(spec["install"]["egress"]), spec["install"]["timeout_s"]),
                   files=MappingProxyType(dict(spec["files"])),
                   run=RunPlan(run["interrupt"], run["stdout"], run["timeout_s"], run["stop_timeout_s"],
                               run.get("credential", "gateway"), tuple(run.get("egress", ()))),
                   report=tuple(spec.get("report", ())))

    @property
    def install_sh(self) -> bytes:
        return (self.path / "install.sh").read_bytes()

    @property
    def dockerfile(self) -> str | None:
        p = self.path / "image.Dockerfile"
        return p.read_text() if p.is_file() else None

    @property
    def home(self) -> Path | None:
        return self.path / "home" if (self.path / "home").is_dir() else None

    @property
    def workspace(self) -> Path | None:
        return self.path / "workspace" if (self.path / "workspace").is_dir() else None


def fields(obj: dict, where: str, required: set[str], optional: set[str] = frozenset()) -> list[str]:
    return ([f"unknown field {where}{k}" for k in sorted(set(obj) - required - optional)]
            + [f"missing {where}{k}" for k in sorted(required - set(obj))])


def positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def hosts(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(h, str) and HOST.fullmatch(h) for h in value)


def relative(rel: Any) -> bool:
    p = PurePosixPath(rel) if isinstance(rel, str) and rel else None
    return bool(p) and not p.is_absolute() and ".." not in p.parts and "\\" not in rel


def schema(s: dict) -> list[str]:
    """Everything wrong with a harness.json, by field."""
    top = {"contract", "name", "description", "provider", "apis", "install", "files", "run"}
    p = fields(s, "", top, {"report"})
    if any(problem.startswith("missing") for problem in p):
        return p
    if s["contract"] != CONTRACT or isinstance(s["contract"], bool):
        p.append(f"contract must be {CONTRACT}, the only contract this server knows")
    if not isinstance(s["name"], str) or not NAME.fullmatch(s["name"]):
        p.append("name must be [a-z0-9-]+, at most 63 characters")
    if not isinstance(s["description"], str) or not s["description"].strip() or "\n" in s["description"]:
        p.append("description must be one line")
    apis = s["apis"]
    if not isinstance(apis, list) or not apis or not all(a in APIS for a in apis) or len(set(apis)) < len(apis):
        p.append(f"apis must name each shape it speaks once, of {', '.join(APIS)}")
        apis = []
    provider = s["provider"]
    if not isinstance(provider, dict) or (bad := fields(provider, "provider.", {"url", "api"})):
        p += bad if isinstance(provider, dict) else ["provider must be {url, api}"]
    elif provider["api"] not in apis:
        p.append("provider.api must be one of apis")
    else:
        try:
            check_provider_url(provider["url"], provider["api"])
        except Invalid as e:
            p.append(f"provider.url: {e}")
    install = s["install"]
    if not isinstance(install, dict) or (bad := fields(install, "install.", {"egress", "timeout_s"})):
        p += bad if isinstance(install, dict) else ["install must be {egress, timeout_s}"]
    else:
        if not hosts(install["egress"]):
            p.append("install.egress must be a list of host or host:port")
        if not positive(install["timeout_s"]):
            p.append("install.timeout_s must be a positive number")
    files = s["files"]
    if not isinstance(files, dict) or not all(relative(k) and not k.startswith(".git/") and isinstance(v, str)
                                              for k, v in files.items()):
        p.append("files must map paths inside the workspace (not .git/) to templates")
    p += run_problems(s["run"])
    report = s.get("report", [])
    if not isinstance(report, list) or not all(relative(g) for g in report):
        p.append("report must be a list of globs relative to $HOME")
    return p


def run_problems(run: Any) -> list[str]:
    if not isinstance(run, dict):
        return ["run must be an object"]
    p = fields(run, "run.", {"interrupt", "stdout", "timeout_s", "stop_timeout_s"}, {"credential", "egress"})
    if any(problem.startswith("missing") for problem in p):
        return p
    if run["interrupt"] not in INTERRUPTS:
        p.append(f"run.interrupt must be one of {', '.join(INTERRUPTS)}")
    if not isinstance(run["stdout"], str) or not CONTENT_TYPE.fullmatch(run["stdout"]):
        p.append("run.stdout must be a content type, such as application/x-ndjson")
    for name in ("timeout_s", "stop_timeout_s"):
        if not positive(run[name]):
            p.append(f"run.{name} must be a positive number")
    if run.get("credential", "gateway") not in CREDENTIALS:
        p.append(f"run.credential must be one of {', '.join(CREDENTIALS)}")
    if not hosts(run.get("egress", [])):
        p.append("run.egress must be a list of host or host:port")
    return p


def folder_problems(path: Path) -> list[str]:
    """Everything wrong with the folder's files beside harness.json."""
    p = []
    if (path / "hi_adapter.py").is_file() and (path / "hi_adapter.py").read_bytes() != CANONICAL_ADAPTER.read_bytes():
        p.append(f"hi_adapter.py differs from the one this server ships ({CANONICAL_ADAPTER}): copy it unchanged")
    for name in ("home", "workspace"):
        d = path / name
        if d.exists() and not d.is_dir():
            p.append(f"{name} must be a directory")
        elif d.is_dir():
            links = [str(x.relative_to(path)) for x in d.rglob("*") if x.is_symlink()]
            p += [f"{link} is a link: a folder's artifacts are files" for link in links]
            p += [f"{x.relative_to(path)} is internal to a workspace" for x in d.rglob("*")
                  if name == "workspace" and x.is_file() and internal(x.relative_to(d).as_posix())]
    dockerfile = path / "image.Dockerfile"
    if dockerfile.exists():
        lines = [line.strip() for line in dockerfile.read_text().splitlines() if line.strip()
                 and not line.lstrip().startswith("#")] if dockerfile.is_file() else []
        if not lines or lines[0] != BASE_FROM:
            p.append(f"image.Dockerfile must start with `{BASE_FROM}`, the base image it builds on")
    return p
