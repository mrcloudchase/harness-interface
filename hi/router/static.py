from __future__ import annotations

from ..models import Decision, RunRequest


class StaticRouter:
    def __init__(self, default: str):
        self.default = default

    async def choose(self, request: RunRequest, cards: list[dict]) -> Decision:
        return Decision(harness=self.default, reason="static default")
