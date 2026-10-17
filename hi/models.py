"""The resource schemas (what people author) and the records (what the server stamps on them).

Authored:  HarnessSpec, RouteSpec, RunRequest.
Stamped:   Harness, Route, Session, Run, Contest, Decision, Verdict.
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
    description: str                                 # for people; Jev routes on the record, not on this
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
        """The harness as a contestant: who it is, nothing about how to run. The service adds its record."""
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


class JudgeSpec(BaseModel):
    """How a run gets its verdict: Jev reads the task and the output and answers these questions;
    `success_when` over the answers decides."""
    model: str = "jev-latest"
    questions: dict[str, Question]
    success_when: str                                # "<answer.path> <op> <value>"

    @model_validator(mode="after")
    def _refs(self) -> "JudgeSpec":
        root = self.success_when.split()[0].split(".")[0]
        if root not in self.questions:
            raise ValueError(f"success_when refers to unknown question '{root}'")
        return self


class ArenaSpec(BaseModel):
    """How a fan-out contest is settled: one choice question over the delivered outputs."""
    model: str = "jev-latest"
    instructions: str = "Which output best accomplishes the task?"


class RouteSpec(BaseModel):
    """The policy: how `route` mode picks a harness, how every run is judged, how a contest is won."""
    kind: Literal["Route"] = "Route"
    engine: Literal["static", "jev"] = "static"
    model: str = "jev-latest"
    state: dict[str, str] = {}                       # templated; what Jev is shown
    questions: dict[str, Question] = {}
    decide: list[Rule] = []
    default: str                                     # the harness when nothing else decides
    judge: JudgeSpec | None = None                   # every finished run's verdict
    arena: ArenaSpec = ArenaSpec()

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


Mode = Literal["fanout", "route", "named"]


class RunRequest(BaseModel):
    """`fanout` sends the task to every harness and a referee picks the winner. `route` asks the
    route for one. `named` is the harness given, or the session's. Left out, the mode is `named`
    when a harness or session is given and `fanout` otherwise."""
    task: str
    instructions: str = ""
    model: str | None = None
    mode: Mode | None = None
    harness: str | None = None
    session: str | None = None                       # continue; the harness is the session's
    files: list[FileIn] = []
    stream: bool = True

    @model_validator(mode="after")
    def _mode(self) -> "RunRequest":
        pinned = bool(self.harness or self.session)
        if self.mode is None:
            self.mode = "named" if pinned else "fanout"
        if (self.mode == "named") != pinned:
            raise ValueError("mode 'named' takes a harness or a session; the other modes take neither")
        return self


class Decision(BaseModel):
    harness: str
    confidence: float | None = None
    runner_up: str | None = None
    reason: str
    answers: dict[str, Any] = {}


class Verdict(BaseModel):
    """The one label on a run: did it deliver the task. From the harness's own status, from the
    judge, or from a person. Later verdicts replace earlier ones; `by` says which."""
    success: bool
    by: Literal["status", "jev", "human"]
    score: float | None = None                       # the judge's probability, when it gave one
    note: str = ""
    answers: dict[str, Any] = {}
    at: float = Field(default_factory=time.time)


class VerdictIn(BaseModel):
    success: bool
    note: str = ""


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
    mode: Mode
    contest: str | None = None                       # the fan-out contest this run entered
    request: RunRequest
    decision: Decision | None = None                 # `route` mode only
    status: Literal["running", "ok", "fail", "timeout", "cancelled"] = "running"
    exit_code: int | None = None
    output: dict[str, Any] = {}                      # what the harness wrote to HI_OUTPUT
    usage: dict[str, Any] | None = None
    files: list[str] = []
    verdict: Verdict | None = None
    started_at: float = Field(default_factory=time.time)
    ended_at: float | None = None
    latency_s: float | None = None


class Contest(BaseModel):
    """One fan-out request: the same task to every harness, one winner. Wins and losses on the
    cards come only from here; a `void` contest (the referee could not decide) counts for nothing."""
    id: str = Field(default_factory=lambda: new_id("c"))
    request: RunRequest
    runs: dict[str, str] = {}                        # harness -> run id
    status: Literal["running", "done", "void"] = "running"
    winner: str | None = None                        # harness; None when nothing was delivered
    session: str | None = None                       # the winner's session, to continue from
    answers: dict[str, Any] = {}                     # the referee's answers, when it was asked
    note: str = ""
    started_at: float = Field(default_factory=time.time)
    ended_at: float | None = None
