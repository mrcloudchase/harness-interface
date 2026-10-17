"""The three resources you manage, the request, and the record the server writes.

Resources:  Provider, Sandbox, Harness.
Wire:       ResponseRequest in, Response out (OpenAI's Responses shape, plus one `harness` key).
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

NAME = r"^[a-z0-9][a-z0-9-]*$"


# ── resources ───────────────────────────────────────────────────────────────────────────────────
class Provider(BaseModel):
    """Where model calls go and what unlocks them. The harness decides which variables want them."""
    name: str = Field(pattern=NAME)
    url: str
    key: str

    @property
    def host(self) -> str:
        from urllib.parse import urlsplit
        u = urlsplit(self.url)
        return f"{u.hostname}:{u.port or (443 if u.scheme == 'https' else 80)}"


class Sandbox(BaseModel):
    """A Dockerfile, and the hosts a run may reach besides its provider."""
    name: str = Field(pattern=NAME)
    dockerfile: str
    egress: list[str] = []                           # host or host:port; the provider's host is always allowed


class RunSpec(BaseModel):
    argv: list[str] = ["bash", "{harness_dir}/run.sh"]
    env: dict[str, str] = {}                         # templated; on top of the contract variables
    stdout: str = "application/x-ndjson"             # what the harness prints; kept as its output
    timeout_s: int = 900


class Harness(BaseModel):
    """Everything needed to run one CLI: its scripts, its command, the files it wants in the
    workspace, and by name the provider it calls and the sandbox it runs in."""
    name: str = Field(pattern=NAME)
    description: str = ""
    provider: str
    sandbox: str = "default"
    files: dict[str, str] = {}                       # path -> templated content, written before the run
    run: RunSpec = RunSpec()
    scripts: dict[str, str] = {}                     # filename -> content, mounted at {harness_dir}


# ── the request: OpenAI's Responses shape ───────────────────────────────────────────────────────
class InputText(BaseModel):
    type: Literal["input_text"]
    text: str


class InputFile(BaseModel):
    type: Literal["input_file"]
    filename: str
    file_data: str                                   # the file's text


class ResponseRequest(BaseModel):
    model: str                                       # "<harness>" or "<harness>/<model>"
    input: str | list[InputText | InputFile]
    instructions: str = ""
    previous_response_id: str | None = None
    stream: bool = False
    metadata: dict[str, Any] = {}

    @property
    def harness(self) -> str:
        return self.model.partition("/")[0]

    @property
    def model_name(self) -> str:
        return self.model.partition("/")[2]

    @property
    def task(self) -> str:
        if isinstance(self.input, str):
            return self.input
        return "\n".join(i.text for i in self.input if isinstance(i, InputText))

    @property
    def files(self) -> dict[str, str]:
        if isinstance(self.input, str):
            return {}
        return {i.filename: i.file_data for i in self.input if isinstance(i, InputFile)}

    @model_validator(mode="after")
    def _some_task(self) -> "ResponseRequest":
        if not self.task.strip():
            raise ValueError("input carries no text")
        return self


# ── the record ──────────────────────────────────────────────────────────────────────────────────
Status = Literal["in_progress", "completed", "failed", "incomplete", "cancelled"]


class HarnessInfo(BaseModel):
    """What the Responses shape has no field for."""
    name: str
    provider: str
    sandbox: str
    runtime: str
    image: str | None = None
    workspace: str
    session_id: str | None = None                    # the harness's own resume handle
    exit_code: int | None = None
    latency_s: float | None = None
    cost_usd: float | None = None
    files: list[str] = []


class Response(BaseModel):
    id: str = Field(default_factory=lambda: f"resp_{uuid.uuid4().hex[:16]}")
    object: Literal["response"] = "response"
    created_at: float = Field(default_factory=time.time)
    status: Status = "in_progress"
    model: str
    instructions: str = ""
    input: str | list[InputText | InputFile]
    previous_response_id: str | None = None
    output: list[dict[str, Any]] = []
    usage: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    incomplete_details: dict[str, str] | None = None
    metadata: dict[str, Any] = {}
    harness: HarnessInfo

    def finish(self, status: str, exit_code: int, output: dict[str, Any], files: list[str]) -> None:
        """Fold what the harness reported into the record. `status` is the run's: ok, fail,
        timeout or cancelled."""
        self.harness.exit_code, self.harness.files = exit_code, files
        self.harness.latency_s = round(time.time() - self.created_at, 3)
        self.harness.session_id = str(output["session_id"]) if output.get("session_id") else self.harness.session_id
        cost = output.get("cost_usd")
        self.harness.cost_usd = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
        self.usage = output.get("usage") if isinstance(output.get("usage"), dict) else None
        answer = output.get("answer")
        self.output = ([{"type": "message", "role": "assistant", "status": "completed",
                         "content": [{"type": "output_text", "text": str(answer), "annotations": []}]}]
                       if isinstance(answer, str) and answer.strip() else [])
        if status == "ok":
            self.status = "completed"
        elif status == "timeout":
            self.status, self.incomplete_details = "incomplete", {"reason": "timeout"}
        elif status == "cancelled":
            self.status = "cancelled"
        else:
            self.status, self.error = "failed", {"code": "harness_failed", "message": f"harness status {status}, exit {exit_code}"}
