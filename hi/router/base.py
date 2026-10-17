from __future__ import annotations

from typing import Protocol

from ..models import Decision, RunRequest


class Rejected(Exception):
    """The route decided no harness should run this."""


class Router(Protocol):
    async def choose(self, request: RunRequest, cards: list[dict]) -> Decision: ...
