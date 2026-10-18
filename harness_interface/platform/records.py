"""Layer 6: the record of one turn. Written when the turn starts, finished when it ends, kept after.
Front ends shape it for their wire; the platform only keeps it true."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from ..harness import Result

Status = Literal["running", "completed", "failed", "timed_out", "cancelled"]


def new_id() -> str:
    return f"resp_{uuid.uuid4().hex[:16]}"


@dataclass
class Record:
    id: str
    model: str                                       # as asked: "harness" or "harness/model"
    harness: str
    provider: str
    sandbox: str
    runtime: str                                     # where it ran: "docker" or "local"
    workspace: str                                   # the conversation's
    previous_id: str | None = None
    session_id: str = ""                             # the harness's own resume handle
    image: str | None = None
    request: dict[str, Any] = field(default_factory=dict)      # the front end's own copy, kept as given
    created_at: float = field(default_factory=time.time)
    status: Status = "running"
    exit_code: int | None = None
    latency_s: float | None = None
    answer: str = ""
    usage: dict[str, Any] | None = None
    cost_usd: float | None = None
    files: list[str] = field(default_factory=list)  # added or modified by this turn
    deleted: list[str] = field(default_factory=list)
    base: str = ""                                   # the workspace's commit before the turn
    commit: str = ""                                 # and after it
    error_code: str = ""                             # harness_failed, setup_failed, server_restarted, internal_error
    error: str = ""

    def finish(self, result: Result) -> None:
        """Fold what the turn came to into the record."""
        self.latency_s = round(time.time() - self.created_at, 3)
        self.exit_code, self.answer, self.usage, self.cost_usd = result.exit_code, result.answer, result.usage, result.cost_usd
        self.files, self.deleted, self.commit = list(result.files), list(result.deleted), result.commit
        self.session_id = result.session_id or self.session_id
        if result.status == "ok":
            self.status = "completed"
        elif result.status == "timeout":
            self.status = "timed_out"
        elif result.status == "cancelled":
            self.status = "cancelled"
        elif result.error:
            self.status, self.error_code, self.error = "failed", "setup_failed", result.error
        else:
            self.status, self.error_code = "failed", "harness_failed"
            self.error = f"harness status fail, exit {result.exit_code}"

    def fail(self, code: str, why: str) -> None:
        """End a record whose turn the platform lost: a restart, or a bug."""
        self.latency_s = self.latency_s or round(time.time() - self.created_at, 3)
        self.status, self.error_code, self.error = "failed", code, why
