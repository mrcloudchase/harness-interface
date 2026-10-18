"""Layer 5: a request names its harness, and a conversation stays on its harness."""
import pytest

from harness_interface.errors import Invalid
from harness_interface.routing import ByName, Route


def test_the_name_chooses():
    assert ByName().route("claude-code") == Route("claude-code", "")
    assert ByName().route("claude-code/claude-opus-5-5") == Route("claude-code", "claude-opus-5-5")


def test_a_conversation_stays_on_its_harness():
    assert ByName().route("codex", conversation="codex").harness == "codex"
    with pytest.raises(Invalid, match="stays on its harness"):
        ByName().route("claude-code", conversation="codex")


def test_a_request_must_name_one():
    with pytest.raises(Invalid):
        ByName().route("/model-only")
