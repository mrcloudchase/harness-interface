"""Everything a task works with, built once per run: the configuration, GitHub, the checkout, the
harness-interface runtime (only for tasks that run agents) and the governor."""
from __future__ import annotations

from dataclasses import dataclass

from config import Config


@dataclass
class Context:
    config: Config
    gh: object
    workspace: object
    governor: object
    runtime: object = None

    def dispatch(self, task: str, item: str | int = "") -> None:
        """Start the next task. A workflow's own actions start no new runs, so Keeper chains its
        steps through workflow_dispatch, which they do."""
        self.gh.dispatch(task, item, ref=self.config.work)
