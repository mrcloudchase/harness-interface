"""Layer 0: a Spec can't be built wrong, data can't change once made, an Outcome is one of four."""
import asyncio
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from harness_interface.errors import Invalid
from harness_interface.execution import Event, NeverStarted, Outcome, Spec


def test_a_spec_is_whole_and_fixed():
    env = {"A": "1"}
    spec = Spec(["echo", "hi"], input=b"x", env=env, workspace="/tmp", timeout_s=5)
    assert spec.command == ("echo", "hi") and spec.workspace == Path("/tmp")
    env["A"] = "changed"                             # the caller's dict is not the spec's
    assert spec.env["A"] == "1"
    with pytest.raises(TypeError):
        spec.env["A"] = "2"
    with pytest.raises(FrozenInstanceError):
        spec.command = ("other",)


@pytest.mark.parametrize("kwargs", [
    {"command": []},
    {"command": [""]},
    {"command": ["echo", 3]},
    {"command": ["echo"], "input": "text, not bytes"},
    {"command": ["echo"], "env": {"A": 1}},
    {"command": ["echo"], "env": {"": "x"}},
    {"command": ["echo"], "timeout_s": 0},
    {"command": ["echo"], "timeout_s": -1},
])
def test_a_spec_refuses_what_cannot_run(kwargs):
    with pytest.raises(Invalid):
        Spec(**kwargs)


def test_an_outcome_is_one_of_four():
    assert Outcome.exited(0).ok and not Outcome.exited(3).ok
    assert not Outcome.timed_out().ok and not Outcome.cancelled().ok and not Outcome.failed("no").ok
    assert Outcome.exited(3).code == 3 and Outcome.failed("no image").reason == "no image"


@pytest.mark.parametrize("bad", [
    lambda: Outcome("finished"),                     # not a kind
    lambda: Outcome("exited"),                       # an exit without a code
    lambda: Outcome("timed_out", code=0),            # a code without an exit
    lambda: Outcome("failed"),                       # a failure without a reason
    lambda: Outcome("cancelled", reason="why"),      # a reason without a failure
])
def test_an_outcome_cannot_be_two_things(bad):
    with pytest.raises(AssertionError):
        bad()


def test_an_event_is_some_bytes_on_a_stream():
    assert Event("stdout", b"x").data == b"x"
    for bad in (lambda: Event("", b"x"), lambda: Event("stdout", b""), lambda: Event("stdout", "x")):
        with pytest.raises(AssertionError):
            bad()


def test_never_started_is_a_failed_execution():
    async def go():
        e = NeverStarted("no such program")
        assert [x async for x in e.events()] == []
        e.cancel()                                   # nothing to stop
        assert await e.wait() == Outcome.failed("no such program")
        with pytest.raises(Invalid):
            await e.send(b"x")
    asyncio.run(go())
