"""What Keeper reports, computed from GitHub every time and stored nowhere: work in flight, what
waits on the human, how loops ended, spend and cost per accepted change. The status issue and the
digest both read it."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from governor import LABEL, week_ago
from memory import Memory, today


@dataclass
class Metrics:
    in_flight: list[dict] = field(default_factory=list)       # open Keeper pull requests
    waiting: list[dict] = field(default_factory=list)         # open items labelled needs-human
    ready: list[dict] = field(default_factory=list)           # issues labelled agent:ready
    ends: Counter = field(default_factory=Counter)            # (loop, end) → count, this week
    regressions: int = 0
    spend_day: float = 0.0
    spend_week: float = 0.0
    accepted: int = 0
    accepted_cost: float = 0.0

    @property
    def cost_per_accepted(self) -> float | None:
        return round(self.accepted_cost / self.accepted, 4) if self.accepted else None


def collect(gh) -> Metrics:
    m = Metrics()
    m.in_flight = [p for p in gh.pulls() if p["head"]["ref"].startswith("keeper/")]
    m.waiting = gh.issues(labels="needs-human", prs=True)
    m.ready = gh.issues(labels="agent:ready")
    since = week_ago()
    for issue in gh.issues(labels=LABEL, state="all", since=f"{since}T00:00:00Z", prs=True):
        if any(label["name"] == "regression" for label in issue.get("labels", [])):
            m.regressions += 1
        s = Memory.load(gh, issue["number"]).state
        m.spend_day += s.spent(today())
        m.spend_week += s.spent(since)
        if s.loop and s.end:
            m.ends[(s.loop, s.end)] += 1
            if s.end == "success":
                m.accepted += 1
                m.accepted_cost += s.spent()
    m.spend_day, m.spend_week = round(m.spend_day, 4), round(m.spend_week, 4)
    return m


def links(items: list[dict]) -> str:
    return "\n".join(f"- #{i['number']} {i['title']}" for i in items) or "- nothing"


def render(m: Metrics, budget) -> str:
    ends = "\n".join(f"| {loop} | {end} | {n} |" for (loop, end), n in sorted(m.ends.items())) or "| — | — | 0 |"
    cpa = f"${m.cost_per_accepted:.2f}" if m.cost_per_accepted is not None else "—"
    return f"""## Waiting on you
{links(m.waiting)}

## In flight
{links(m.in_flight)}

## Ready for an agent
{links(m.ready)}

## Loops this week
| Loop | End state | Count |
|---|---|---|
{ends}

## Health and cost
- Regressions this week: {m.regressions}
- Spend today: ${m.spend_day:.2f} of ${budget.day_usd:.2f}; this week: ${m.spend_week:.2f} of ${budget.week_usd:.2f}
- Accepted changes this week: {m.accepted}; cost per accepted change: {cpa}"""
