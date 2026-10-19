"""The brakes every agent turn passes first: the pause switch, the budgets and the open-PR limit.
Spend is summed from the state comments on the items Keeper worked on this week."""
from __future__ import annotations

import time

from memory import Memory, today

LABEL = "keeper"                             # every item Keeper works on carries it


def week_ago() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))


class Governor:
    def __init__(self, config, gh, enabled: bool):
        self.config, self.gh, self.enabled = config, gh, enabled
        self._spend: tuple[float, float] | None = None

    def spend(self) -> tuple[float, float]:
        """Today's and this week's spend, from every Keeper item touched this week."""
        if self._spend is None:
            day, week = 0.0, 0.0
            since = week_ago()
            for issue in self.gh.issues(labels=LABEL, state="all", since=f"{since}T00:00:00Z", prs=True):
                state = Memory.load(self.gh, issue["number"]).state
                day, week = day + state.spent(today()), week + state.spent(since)
            self._spend = (round(day, 4), round(week, 4))
        return self._spend

    def allow(self, run_spent: float = 0.0, opening_pr: bool = False) -> tuple[bool, str]:
        b = self.config.budget
        if not self.enabled:
            return False, "Keeper is paused (KEEPER_ENABLED is not true)"
        if run_spent >= b.run_usd:
            return False, f"this run spent ${run_spent:.2f} of its ${b.run_usd:.2f}"
        day, week = self.spend()
        if day + run_spent >= b.day_usd:
            return False, f"today's budget is spent (${day + run_spent:.2f} of ${b.day_usd:.2f})"
        if week + run_spent >= b.week_usd:
            return False, f"this week's budget is spent (${week + run_spent:.2f} of ${b.week_usd:.2f})"
        if opening_pr and sum(p["head"]["ref"].startswith("keeper/") for p in self.gh.pulls()) >= b.open_prs:
            return False, f"{b.open_prs} Keeper pull requests are already open"
        return True, ""
