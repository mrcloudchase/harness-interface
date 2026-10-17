import pytest

from hi.models import Rule
from hi.router.rules import decide, holds

ANSWERS = {"harness": {"choice": "codex", "confidence": 0.82, "runner_up": "claude-code"},
           "risky": {"probability": 0.1}, "size": {"level": 2}}


def test_holds():
    assert holds("harness.confidence >= 0.8", ANSWERS)
    assert not holds("harness.confidence > 0.9", ANSWERS)
    assert holds("harness.choice == codex", ANSWERS)
    assert holds(None, ANSWERS)
    assert not holds("missing.x > 0", ANSWERS)


def test_decide_in_order():
    rules = [Rule(when="risky.probability > 0.8", then="reject needs a person"),
             Rule(when="harness.confidence >= 0.6", then="use harness.choice"),
             Rule(then="use default")]
    assert decide(rules, ANSWERS, "claude-code") == ("codex", "use harness.choice")
    low = {**ANSWERS, "harness": {**ANSWERS["harness"], "confidence": 0.3}}
    assert decide(rules, low, "claude-code") == ("claude-code", "use default")
    hot = {**ANSWERS, "risky": {"probability": 0.95}}
    assert decide(rules, hot, "claude-code")[0] == "reject:needs a person"


def test_bad_rule():
    with pytest.raises(ValueError):
        holds("garbage", ANSWERS)
