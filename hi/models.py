"""The resource schemas (what people author) and the records (what the server stamps on them).

Authored:  HarnessSpec, RouteSpec, RunRequest.
Stamped:   Harness, Route, Session, Run, Decision.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── Harness: a command, and how the request reaches it ──────────────────────────────────────────
class RunSpec(BaseModel):
    argv: list[str]                                  # templated; see hi/template.py for the context
    env: dict[str, str] = {}                         # templated; overlaid on the server's environment
    stdout: str = "application/x-ndjson"             # content type the response body is forwarded as
    timeout_s: int = 900


class HarnessSpec(BaseModel):
    kind: Literal["Harness"] = "Harness"
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str                                 # the routing prompt: what Jev reads to choose this
    labels: list[str] = []
    models: list[str] = []
    secrets: list[str] = []                          # env names injected from the secret store
    files: dict[str, str] = {}                       # path -> templated content, written before the run
    run: RunSpec
    check: list[str] | None = None                   # readiness probe run at apply time
    dir: str | None = None                           # where the spec came from; {harness_dir} in templates


class Harness(HarnessSpec):
    version: int = 1
    check_ok: bool | None = None
    check_output: str = ""
    applied_at: float = Field(default_factory=time.time)

    def card(self) -> dict[str, Any]:
        """What the router sees: enough to choose, nothing about how to run."""
        return {"name": self.name, "description": self.description,
                "labels": self.labels, "models": self.models}


# ── Route: the decision, authored in Jev's own question types ───────────────────────────────────
class Question(BaseModel):
    type: Literal["choice", "noul", "score"]
    instructions: str
    # choice: {option: description} or "from_registry"; score: ordered level descriptions; noul: none
    criteria: dict[str, str] | list[str] | Literal["from_registry"] | None = None

    @model_validator(mode="after")
    def _shape(self) -> "Question":
        if self.type == "choice" and not (isinstance(self.criteria, dict) or self.criteria == "from_registry"):
            raise ValueError("a choice needs criteria: {option: description} or 'from_registry'")
        if self.type == "score" and not isinstance(self.criteria, list):
            raise ValueError("a score needs criteria: an ordered list of level descriptions")
        return self


class Rule(BaseModel):
    when: str | None = None                          # "<answer.path> <op> <value>"; None = always
    then: str                                        # "use <harness>" | "use <answer.path>" | "reject <message>"


class RouteSpec(BaseModel):
    kind: Literal["Route"] = "Route"
    engine: Literal["static", "jev"] = "static"
    model: str = "jev-latest"
    state: dict[str, str] = {}                       # templated; what Jev is shown
    questions: dict[str, Question] = {}
    decide: list[Rule] = []
    default: str                                     # the harness when nothing else decides

    @model_validator(mode="after")
    def _refs(self) -> "RouteSpec":
        for r in self.decide:
            for expr in (r.when, r.then if "." in r.then else None):
                if expr:
                    root = expr.split()[-1 if expr is r.then else 0].split(".")[0]
                    if root not in self.questions:
                        raise ValueError(f"rule refers to unknown question '{root}'")
        return self


class Route(RouteSpec):
    version: int = 1
    applied_at: float = Field(default_factory=time.time)


# ── Request and what the server records about it ────────────────────────────────────────────────
class FileIn(BaseModel):
    name: str
    content: str


class RunRequest(BaseModel):
    task: str
    instructions: str = ""
    model: str | None = None
    harness: str | None = None                       # pin; skips the router
    session: str | None = None                       # continue; harness is the session's
    files: list[FileIn] = []
    check: str | None = None                         # shell command run in the workspace afterwards
    stream: bool = True


class Decision(BaseModel):
    harness: str
    confidence: float | None = None
    runner_up: str | None = None
    reason: str
    answers: dict[str, Any] = {}


class Session(BaseModel):
    id: str = Field(default_factory=lambda: new_id("s"))
    harness: str
    session_id: str | None = None                    # the harness's own resume handle
    workspace: str
    created_at: float = Field(default_factory=time.time)


class Run(BaseModel):
    id: str = Field(default_factory=lambda: new_id("r"))
    session: str
    harness: str
    request: RunRequest
    decision: Decision | None = None
    status: Literal["running", "ok", "fail", "timeout", "cancelled"] = "running"
    exit_code: int | None = None
    output: dict[str, Any] = {}                      # what the harness wrote to HI_OUTPUT
    usage: dict[str, Any] | None = None
    files: list[str] = []
    check: dict[str, Any] | None = None
    started_at: float = Field(default_factory=time.time)
    ended_at: float | None = None
    latency_s: float | None = None
