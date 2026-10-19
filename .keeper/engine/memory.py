"""A task's state between runs, kept on GitHub as one hidden comment on its issue or pull request:
the loop, attempts, the turns' response ids, what each spent, the last failure and the end state.
Spend is read from these comments and nowhere else."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field

MARK = "<!-- keeper:state "
END = " -->"


def today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


@dataclass
class State:
    loop: str = ""
    attempts: int = 0
    responses: list[str] = field(default_factory=list)
    spend: list[list] = field(default_factory=list)      # [[date, usd], …], one per turn
    failure: str = ""                                    # a fingerprint of the last failure
    end: str = ""
    branch: str = ""
    data: dict = field(default_factory=dict)             # what a job keeps: last green commit, streaks

    def spent(self, since: str = "") -> float:
        return round(sum(usd for day, usd in self.spend if day >= since), 4)


def parse(body: str) -> State | None:
    start = body.find(MARK)
    if start < 0:
        return None
    raw = body[start + len(MARK):body.find(END, start)]
    try:
        return State(**json.loads(raw))
    except (ValueError, TypeError):
        return None


def render(state: State, text: str = "") -> str:
    return f"{text}\n\n{MARK}{json.dumps(asdict(state))}{END}".strip()


def fingerprint(reasons: str) -> str:
    return hashlib.sha256(" ".join(reasons.split()).encode()).hexdigest()[:16]


class Memory:
    """The state comment on one issue or pull request."""

    def __init__(self, gh, item: int, state: State | None = None, comment_id: int | None = None):
        self.gh, self.item, self.state, self._comment = gh, item, state or State(), comment_id

    @classmethod
    def load(cls, gh, item: int) -> Memory:
        for c in gh.comments(item):
            if (s := parse(c["body"])) is not None:
                return cls(gh, item, s, c["id"])
        return cls(gh, item)

    def save(self, text: str = "Keeper's working state for this item.") -> None:
        body = render(self.state, text)
        if self._comment:
            self.gh.edit_comment(self._comment, body)
        else:
            self._comment = self.gh.comment(self.item, body)["id"]

    def record(self, response_id: str, usd: float) -> None:
        """A turn: its response id and what it spent. Attempts are counted by the loop."""
        self.state.responses.append(response_id)
        self.state.spend.append([today(), round(usd, 4)])
        self.save()

    def failed(self, reasons: str) -> bool:
        """Record a failure; True if it is the same as the last one, which means no progress."""
        f = fingerprint(reasons)
        same, self.state.failure = f == self.state.failure, f
        self.save()
        return same


class Scratch(Memory):
    """Memory that is never written to GitHub: for replaying past tasks."""

    def __init__(self):
        super().__init__(None, 0)

    def save(self, text: str = "") -> None:
        pass
