"""Layer 6: a turn in flight. Its record, every event so far, and the turn itself. Any number of
clients can follow it, each from the start, and come and go; following never steers the run."""
from __future__ import annotations

import asyncio
import dataclasses
from typing import AsyncIterator

from ..execution import Event
from ..harness import Turn
from .records import Record


class Run:
    def __init__(self, record: Record, turn: Turn):
        self.record, self.turn = record, turn
        self.created = dataclasses.replace(record)   # the record as it was when the turn began
        self.done = asyncio.Event()
        self.task: asyncio.Task | None = None
        self._events: list[Event] = []
        self._news = asyncio.Condition()

    async def publish(self, event: Event) -> None:
        async with self._news:
            self._events.append(event)
            self._news.notify_all()

    async def close(self) -> None:
        async with self._news:
            self.done.set()
            self._news.notify_all()

    async def follow(self) -> AsyncIterator[Event]:
        """Every event, from the first, as it arrives, until the run is done."""
        seen = 0
        while True:
            async with self._news:
                await self._news.wait_for(lambda: len(self._events) > seen or self.done.is_set())
                new, finished = self._events[seen:], self.done.is_set()
            seen += len(new)
            for event in new:
                yield event
            if finished and seen == len(self._events):
                return

    def cancel(self) -> None:
        """Safe from any thread."""
        self.turn.cancel()
