"""Layer 5: which harness serves a request. A Router only decides: it runs, stores and resolves
nothing. Another way to choose is another Router."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import Invalid


@dataclass(frozen=True)
class Route:
    harness: str
    model: str = ""                                  # passed through to the harness, if the request named one


class Router(Protocol):
    def route(self, model: str, conversation: str | None = None) -> Route:
        """Choose for a request. `conversation` is the harness an earlier turn ran on, if it continues one."""
        ...


class ByName:
    """The request names the harness: "harness" or "harness/model". A continued conversation stays
    on its harness."""

    def route(self, model: str, conversation: str | None = None) -> Route:
        harness, _, model_name = model.partition("/")
        if not harness:
            raise Invalid("model must name a harness, as 'harness' or 'harness/model'")
        if conversation and harness != conversation:
            raise Invalid(f"this conversation is on harness '{conversation}'; a conversation stays on its harness")
        return Route(harness, model_name)
