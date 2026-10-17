import asyncio

import pytest

from hi.models import Route, RunRequest
from hi.router.base import Rejected
from hi.router.jev import JevRouter, flatten

CARDS = [{"name": "claude-code", "description": "shell coding agent", "labels": [], "models": []},
         {"name": "codex", "description": "openai coding agent", "labels": [], "models": []}]


class FakeJev:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def evaluate(self, model, state, questions):
        self.calls.append((model, state, questions))
        return self.answers


def route(**over):
    base = {"kind": "Route", "engine": "jev", "default": "claude-code",
            "state": {"task": "{request.task}"},
            "questions": {"harness": {"type": "choice", "instructions": "which?", "criteria": "from_registry"},
                          "risky": {"type": "noul", "instructions": "risky?"}},
            "decide": [{"when": "risky.probability > 0.8", "then": "reject too risky"},
                       {"when": "harness.confidence >= 0.6", "then": "use harness.choice"},
                       {"then": "use default"}]}
    return Route(**{**base, **over})


def test_from_registry_becomes_criteria_and_state_renders():
    fake = FakeJev({"harness": {"type": "choice", "choice": "codex", "confidence": 0.9,
                                "probabilities": {"codex": 0.9, "claude-code": 0.1}},
                    "risky": {"type": "noul", "noul": 0.05}})
    d = asyncio.run(JevRouter(route(), fake).choose(RunRequest(task="add tests"), CARDS))
    assert d.harness == "codex" and d.runner_up == "claude-code" and d.confidence == 0.9
    model, state, questions = fake.calls[0]
    assert state == {"task": "add tests"}
    assert questions["harness"]["criteria"] == {"claude-code": "shell coding agent", "codex": "openai coding agent"}
    assert "criteria" not in questions["risky"]


def test_low_confidence_falls_to_default():
    fake = FakeJev({"harness": {"type": "choice", "choice": "codex", "confidence": 0.4, "probabilities": {}},
                    "risky": {"type": "noul", "noul": 0.0}})
    d = asyncio.run(JevRouter(route(), fake).choose(RunRequest(task="x"), CARDS))
    assert d.harness == "claude-code" and d.reason == "use default" and d.confidence == 0.4


def test_reject():
    fake = FakeJev({"harness": {"type": "choice", "choice": "codex", "confidence": 0.9, "probabilities": {}},
                    "risky": {"type": "noul", "noul": 0.97}})
    with pytest.raises(Rejected):
        asyncio.run(JevRouter(route(), fake).choose(RunRequest(task="rm -rf prod"), CARDS))


def test_flatten_score():
    a = flatten({"type": "score", "score": 1.4, "confidence": 0.5, "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3}})
    assert a["level"] == 1 and a["score"] == 1.4


def test_route_rejects_unknown_question_reference():
    with pytest.raises(ValueError):
        route(decide=[{"when": "nope.x > 1", "then": "use default"}])
