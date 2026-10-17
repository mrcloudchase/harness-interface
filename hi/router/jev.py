"""Jev as the decision engine, three ways. The router picks a harness from the records; the
judge labels a finished run; the referee picks a contest's winner from the delivered outputs.
The policy is authored in Jev's own question types; this module only resolves `from_registry`,
renders the state, makes one call, flattens the answers, and runs the decide table."""
from __future__ import annotations

import json
from typing import Any

import httpx

from ..models import ArenaSpec, Decision, JudgeSpec, Question, Route, Run, RunRequest, Verdict
from ..template import render_obj
from .base import Rejected
from .rules import decide, holds


class JevClient:
    """POST {base}/systemone with {model, state, questions} -> {answers}."""

    def __init__(self, base_url: str, api_key: str, timeout_s: float = 30.0):
        self.base_url, self.api_key, self.timeout_s = base_url.rstrip("/"), api_key, timeout_s

    async def evaluate(self, model: str, state: Any, questions: dict[str, dict]) -> dict[str, dict]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(f"{self.base_url}/systemone",
                                  headers={"Authorization": f"Bearer {self.api_key}"},
                                  json={"model": model, "state": state, "questions": questions})
        r.raise_for_status()
        return r.json().get("answers") or {}


def flatten(answer: dict) -> dict[str, Any]:
    """One flat dict per answer so rules can say `harness.confidence` or `risky.probability`."""
    t = answer.get("type")
    probs = answer.get("probabilities") or {}
    if t == "choice":
        ranked = sorted(probs, key=probs.get, reverse=True)
        return {"choice": answer.get("choice"), "confidence": answer.get("confidence"),
                "runner_up": ranked[1] if len(ranked) > 1 else None, "probabilities": probs}
    if t == "noul":
        return {"probability": answer.get("noul")}
    if t == "score":
        level = max(probs, key=probs.get) if probs else None
        return {"score": answer.get("score"), "level": int(level) if level is not None else None,
                "confidence": answer.get("confidence"), "probabilities": probs}
    return dict(answer)


def compile_questions(questions: dict[str, Question], cards: list[dict] | None = None) -> dict[str, dict]:
    """Jev's wire shape. `from_registry` becomes one option per card: the harness's name and its
    record sentence, nothing else, so the choice is between track records alone."""
    out = {}
    for qid, q in questions.items():
        criteria = q.criteria
        if criteria == "from_registry":
            criteria = {c["name"]: c["record"] for c in (cards or [])}
        out[qid] = {"type": q.type, "instructions": q.instructions,
                    **({"criteria": criteria} if criteria is not None else {})}
    return out


class JevRouter:
    def __init__(self, route: Route, client: JevClient):
        self.route, self.client = route, client

    def questions(self, cards: list[dict]) -> dict[str, dict]:
        return compile_questions(self.route.questions, cards)

    def state(self, request: RunRequest) -> dict[str, str]:
        ctx = {"request": {**request.model_dump(), "file_names": [f.name for f in request.files]}}
        return render_obj(self.route.state, ctx)

    async def choose(self, request: RunRequest, cards: list[dict]) -> Decision:
        raw = await self.client.evaluate(self.route.model, self.state(request), self.questions(cards))
        answers = {qid: flatten(a) for qid, a in raw.items()}
        target, reason = decide(self.route.decide, answers, self.route.default)
        if target.startswith("reject:"):
            raise Rejected(target[len("reject:"):])
        if target not in {c["name"] for c in cards}:
            raise LookupError(f"route chose '{target}', which is not a registered harness")
        # The choice question's own confidence and runner-up, whichever rule decided: a fall to
        # the default still records how sure Jev was of the harness it would have picked.
        choice = next((a for a in answers.values() if "choice" in a), {})
        return Decision(harness=target, confidence=choice.get("confidence"),
                        runner_up=choice.get("runner_up"), reason=reason, answers=answers)


def excerpt(answer: str, files: dict[str, str], answer_chars: int, file_chars: int, max_files: int) -> dict:
    """What a harness produced, cut to size: the tail of its answer and the head of each file."""
    return {"answer": answer[-answer_chars:],
            "files": {k: v[:file_chars] for k, v in list(files.items())[:max_files]}}


class JevJudge:
    """Labels a finished run: Jev reads the task, the instructions, the harness's answer and the
    produced files, and `success_when` over its answers is the verdict."""

    ANSWER_CHARS, FILE_CHARS, MAX_FILES = 8000, 2000, 8

    def __init__(self, spec: JudgeSpec, client: JevClient):
        self.spec, self.client = spec, client

    @classmethod
    def state(cls, run: Run, answer: str, files: dict[str, str]) -> dict:
        return {"task": run.request.task, "instructions": run.request.instructions,
                "harness_status": run.status,
                **excerpt(answer, files, cls.ANSWER_CHARS, cls.FILE_CHARS, cls.MAX_FILES)}

    async def judge(self, run: Run, answer: str, files: dict[str, str]) -> Verdict:
        raw = await self.client.evaluate(self.spec.model, self.state(run, answer, files),
                                         compile_questions(self.spec.questions))
        answers = {qid: flatten(a) for qid, a in raw.items()}
        root = self.spec.success_when.split()[0].split(".")[0]
        lead = answers.get(root, {})
        score = lead.get("probability", lead.get("confidence"))
        return Verdict(success=holds(self.spec.success_when, answers), by="jev",
                       score=float(score) if isinstance(score, (int, float)) else None,
                       note=self.spec.success_when, answers=answers)


class JevReferee:
    """Settles a contest: Jev reads the task and each delivered output, one option per harness,
    and chooses. The options are what was produced, never who produced it beyond the name."""

    ANSWER_CHARS, FILE_CHARS, MAX_FILES = 4000, 1000, 4

    def __init__(self, spec: ArenaSpec, client: JevClient):
        self.spec, self.client = spec, client

    def questions(self, entrants: dict[str, tuple[str, dict[str, str]]]) -> dict[str, dict]:
        criteria = {name: json.dumps(excerpt(answer, files, self.ANSWER_CHARS, self.FILE_CHARS, self.MAX_FILES))
                    for name, (answer, files) in entrants.items()}
        return {"winner": {"type": "choice", "instructions": self.spec.instructions, "criteria": criteria}}

    async def pick(self, request: RunRequest, entrants: dict[str, tuple[str, dict[str, str]]]) -> tuple[str, dict[str, Any]]:
        state = {"task": request.task, "instructions": request.instructions}
        raw = await self.client.evaluate(self.spec.model, state, self.questions(entrants))
        answers = {qid: flatten(a) for qid, a in raw.items()}
        winner = answers.get("winner", {}).get("choice")
        if winner not in entrants:
            raise LookupError(f"referee chose {winner!r}, which did not enter")
        return str(winner), answers
