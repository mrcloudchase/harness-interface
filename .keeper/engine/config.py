"""The project's Keeper configuration: keeper.toml and the loop documents. Checked when loaded, so an
invalid one never runs."""
from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("command", "rule", "live", "judge")
DETERMINISTIC = ("command", "rule")          # every loop needs at least one of these


class ConfigError(ValueError):
    """keeper.toml or a loop document can't be run as written."""


def matches(path: str, patterns) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


@dataclass(frozen=True)
class Verify:
    """One verifier a loop lists."""
    kind: str
    run: str = ""                            # command: a [checks] name, "checks" for all, or "live"
    expect: str = "pass"                     # command: "pass", or "fail" for tests that must fail first
    repeat: int = 1
    rules: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()              # judge: checker roles; empty means [reviewers] for the paths

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ConfigError(f"verifier kind must be one of {KINDS}, not {self.kind!r}")
        if self.expect not in ("pass", "fail") or self.repeat < 1:
            raise ConfigError("a command verifier expects pass or fail, at least once")
        object.__setattr__(self, "rules", tuple(self.rules))
        object.__setattr__(self, "roles", tuple(self.roles))


@dataclass(frozen=True)
class LoopDoc:
    """A loop: what starts it, what it is for, who works, what decides it is done, and its brakes."""
    name: str
    goal: str
    verifiers: tuple[Verify, ...]
    trigger: str = "dispatch"               # "dispatch", "schedule", or a label
    maker: str = "maker"
    escalate: tuple[str, ...] = ("maker",)   # whose harnesses do the maker's work, in order, when one gives up
    tries: int = 0                           # 0: [budget].tries
    then: str = ""                          # the task to dispatch after success or no_op
    opens_pr: bool = True                   # False: the work stays on its branch for `then`
    needs: str = ""                         # a config key that must be set, or the loop is off

    def __post_init__(self) -> None:
        object.__setattr__(self, "verifiers", tuple(v if isinstance(v, Verify) else Verify(**v) for v in self.verifiers))
        object.__setattr__(self, "escalate", tuple(self.escalate))
        if not any(v.kind in DETERMINISTIC for v in self.verifiers):
            raise ConfigError(f"loop {self.name!r} needs a command or rule verifier")
        if self.tries < 0 or not self.goal.strip():
            raise ConfigError(f"loop {self.name!r} needs a goal and non-negative tries")


@dataclass(frozen=True)
class Budget:
    run_usd: float
    day_usd: float
    week_usd: float
    open_prs: int
    tries: int

    def __post_init__(self) -> None:
        if min(self.run_usd, self.day_usd, self.week_usd) <= 0 or self.open_prs < 1 or self.tries < 1:
            raise ConfigError("every budget must be positive")


@dataclass(frozen=True)
class Config:
    root: Path
    human: str
    checks: dict[str, str]
    human_tier: tuple[str, ...]
    reviewers: dict[str, list[str]]
    roles: dict[str, str]
    providers: dict[str, dict[str, str]]
    budget: Budget
    loops: dict[str, LoopDoc]
    schedule: dict[str, list[str]]           # cron → tasks
    live: dict = field(default_factory=dict)
    rigor: dict = field(default_factory=dict)
    upgrade: dict = field(default_factory=dict)
    compat: dict = field(default_factory=dict)
    work: str = "main"                       # where agents' PRs land
    release: str = "main"                    # what releases are cut from
    soak: int = 3                            # green nightlies on `work` before promoting it
    spec: str = ""

    @classmethod
    def load(cls, root: Path) -> Config:
        root = Path(root)
        path = root / "keeper.toml"
        if not path.is_file():
            raise ConfigError(f"{root} has no keeper.toml")
        d = tomllib.loads(path.read_text())
        loops = {}
        for p in sorted((root / ".keeper" / "loops").glob("*.toml")):
            doc = LoopDoc(**tomllib.loads(p.read_text()))
            if doc.name != p.stem:
                raise ConfigError(f"{p.name} names its loop {doc.name!r}")
            loops[doc.name] = doc
        branches = d.get("branches", {})
        try:
            config = cls(root=root, human=d["human"]["login"], checks=d["checks"],
                         human_tier=tuple(d["tiers"]["human"]), reviewers=d.get("reviewers", {"**": []}),
                         roles=d["roles"], providers=d["providers"], budget=Budget(**d["budget"]),
                         loops=loops, schedule=d.get("schedule", {}), live=d.get("live", {}),
                         rigor=d.get("rigor", {}), upgrade=d.get("upgrade", {}), compat=d.get("compat", {}),
                         work=branches.get("work", "main"), release=branches.get("release", "main"),
                         soak=branches.get("soak", 3), spec=d.get("spec", ""))
        except KeyError as e:
            raise ConfigError(f"keeper.toml is missing {e.args[0]!r}") from None
        config.check()
        return config

    def check(self) -> None:
        if not self.checks:
            raise ConfigError("[checks] needs at least one command")
        for role in ("planner", "maker", "checker", "writer"):
            if role not in self.roles:
                raise ConfigError(f"[roles] needs {role!r}")
        prompts = self.root / ".keeper" / "prompts"
        checkers = {r for names in self.reviewers.values() for r in names}
        for doc in self.loops.values():
            for role in (doc.maker, *doc.escalate):
                self.harness(role)
            checkers |= {r for v in doc.verifiers for r in v.roles}
        for role in ("planner", "maker", "writer", *(f"checker-{c}" for c in checkers)):
            if not (prompts / f"{role}.md").is_file():
                raise ConfigError(f"no prompt for role {role!r}: add .keeper/prompts/{role}.md")
        for cron, tasks in self.schedule.items():
            if not tasks:
                raise ConfigError(f"schedule {cron!r} runs nothing")

    def harness(self, role: str) -> str:
        """The harness a role runs on: `checker-security` falls back to `checker`."""
        name = self.roles.get(role) or self.roles.get(role.split("-")[0])
        if not name:
            raise ConfigError(f"no harness for role {role!r}")
        return name

    def is_human_tier(self, path: str) -> bool:
        return matches(path, self.human_tier)

    def reviewers_for(self, paths) -> list[str]:
        """The checker roles a change needs: for each path, the first [reviewers] pattern it matches."""
        roles: list[str] = []
        for path in paths:
            for pattern, names in self.reviewers.items():
                if fnmatch.fnmatchcase(path, pattern):
                    roles += [n for n in names if n not in roles]
                    break
        return roles

    def enabled(self, loop: LoopDoc) -> bool:
        """A loop that needs a setting runs only once the setting is there."""
        if not loop.needs:
            return True
        section, _, key = loop.needs.partition(".")
        return bool(getattr(self, section, {}).get(key))

    def tasks_for(self, cron: str) -> list[str]:
        return list(self.schedule.get(cron, []))
