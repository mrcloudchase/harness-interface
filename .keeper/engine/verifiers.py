"""The checks that decide when work is done, by the level of the ladder they stand on: commands (1),
rules (2), live runs (3), judges (4) and the human (5). Each answers one question about a change:
did it pass, and if not, why. A loop is done only when every verifier it lists passes."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from config import Config, Verify, matches
from roles import RESULT, instructions

TESTS = ("tests/**", "**/test_*.py", "**/*_test.py")


@dataclass(frozen=True)
class Verdict:
    passed: bool
    level: int
    name: str
    reasons: str = ""


@dataclass
class Change:
    """A change under review: where it is, what it touches, and what it is for."""
    config: Config
    workspace: object
    base: str
    paths: list[str]
    task: str = ""                           # the issue's title and body
    pr: dict | None = None                   # set by the Gate
    runtime: object = None                   # for judges
    gh: object = None                        # for the human
    spend: Callable[[dict], None] = lambda record: None    # judges' turns are counted too


# ── level 1: commands ──────────────────────────────────────────────────────────────────────────
def commands(config: Config, run: str) -> dict[str, str]:
    if run == "checks":
        return dict(config.checks)
    if run == "live":
        return {"live": config.live["command"]}
    if run == "compat":
        return {"compat": config.compat["command"]}
    if run == "mutation":
        return {"mutation": config.rigor["mutation"]}
    if run in config.checks:
        return {run: config.checks[run]}
    return {run: run}


def command(v: Verify, change: Change, level: int = 1) -> Verdict:
    failures = []
    for name, cmd in commands(change.config, v.run).items():
        for _ in range(v.repeat):
            ok, out = change.workspace.run(cmd, with_secrets=level == 3)
            if ok != (v.expect == "pass"):
                failures.append(f"`{cmd}` {'failed' if v.expect == 'pass' else 'passed, but must fail first'}:\n{out}")
                break
    return Verdict(not failures, level, f"command:{v.run}", "\n\n".join(failures))


# ── level 2: rules ─────────────────────────────────────────────────────────────────────────────
def is_test(config: Config, path: str) -> bool:
    return matches(path, config.rigor.get("tests", TESTS))


def tests_only_grow(change: Change) -> str:
    """No test file deleted, no test removed, no assertion dropped."""
    c, ws = change.config, change.workspace
    name = re.compile(c.rigor.get("test_pattern", r"def (test_\w+)"))
    asserts = re.compile(c.rigor.get("assert_pattern", r"\bassert\b"))
    problems = []
    for path in [p for p in change.paths if is_test(c, p)]:
        before = ws.file_at(change.base, path)
        if before is None:
            continue
        now = (ws.root / path).read_text() if (ws.root / path).is_file() else None
        if now is None:
            problems.append(f"{path} was deleted")
            continue
        if gone := set(name.findall(before)) - set(name.findall(now)):
            problems.append(f"{path} lost {', '.join(sorted(gone))}")
        if len(asserts.findall(now)) < len(asserts.findall(before)):
            problems.append(f"{path} has fewer assertions than before")
    return "; ".join(problems)


def tests_only(change: Change) -> str:
    other = [p for p in change.paths if not is_test(change.config, p)]
    return f"only tests may change, not {', '.join(other)}" if other else ""


def _size(change: Change, ref: str | None) -> int:
    budget = change.config.rigor["size_budget"]
    ws, glob = change.workspace, f"{budget['path']}/{budget.get('glob', '*')}"
    if ref is None:
        files = [p for p in ws.git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()
                 if matches(p, [glob]) and (ws.root / p).is_file()]
        return sum(len((ws.root / p).read_text(errors="replace").splitlines()) for p in files)
    return sum(len((ws.file_at(ref, p) or "").splitlines()) for p in ws.files_at(ref) if matches(p, [glob]))


def size_budget(change: Change) -> str:
    if "size_budget" not in change.config.rigor:
        return ""
    lines, limit = _size(change, None), change.config.rigor["size_budget"]["lines"]
    return f"{lines} lines, over the budget of {limit}" if lines > limit else ""


def size_decreased(change: Change) -> str:
    before, now = _size(change, change.base), _size(change, None)
    return "" if now < before else f"{now} lines, not fewer than the {before} before"


def keeper_paths(change: Change) -> str:
    other = [p for p in change.paths if not matches(p, (".keeper/loops/*", ".keeper/prompts/*"))]
    return f"Evolve may change only loops and prompts, not {', '.join(other)}" if other else ""


def no_workflows(change: Change) -> str:
    bad = [p for p in change.paths if p.startswith(".github/workflows/")]
    return f"workflows are the human's: {', '.join(bad)}" if bad else ""


def commit_format(change: Change) -> str:
    title = (change.pr or {}).get("title", "")
    return "" if re.match(r"^[\w./-]+: \S", title) else f"the title {title!r} is not `area: summary`"


def themed(change: Change) -> str:
    """A Keeper pull request names the theme it serves."""
    pr = change.pr or {}
    if not pr.get("head", {}).get("ref", "").startswith("keeper/"):
        return ""
    return "" if re.search(r"^Theme: \S", pr.get("body") or "", re.M) else "no `Theme:` trailer"


def verified(change: Change) -> str:
    """A Keeper pull request carries its loop's verdict for exactly this commit."""
    pr = change.pr or {}
    if not pr.get("head", {}).get("ref", "").startswith("keeper/"):
        return ""
    sha = pr["head"]["sha"]
    for c in reversed(change.gh.comments(pr["number"])):
        if (m := re.search(r"<!-- keeper:verdict (\{.*?\}) -->", c["body"])):
            v = json.loads(m.group(1))
            return "" if v.get("sha") == sha and v.get("passed") else "its loop did not verify this commit"
    return "no verdict from its loop"


RULES: dict[str, Callable[[Change], str]] = {f.__name__: f for f in (
    tests_only_grow, tests_only, size_budget, size_decreased, keeper_paths, no_workflows, commit_format, themed, verified)}


def rule(v: Verify, change: Change) -> Verdict:
    problems = [f"{r}: {p}" for r in v.rules if (p := RULES[r](change))]
    return Verdict(not problems, 2, "rules", "\n".join(problems))


# ── level 3: live ──────────────────────────────────────────────────────────────────────────────
def live(v: Verify, change: Change) -> Verdict:
    return command(Verify("command", run=v.run or "live"), change, level=3)


# ── level 4: judges ────────────────────────────────────────────────────────────────────────────
REVIEW = """Review this change. The task it serves is below, the diff is in change.diff, and the
project's files are in your working directory as the change leaves them. Judge it against the task,
the project's principles and your role. Do not change any project files.

Write keeper.json: {{"verdict": "approve" | "changes", "findings": "<what must change, citing file:line; empty to approve>"}}

## The task
{task}"""


def judge(v: Verify, change: Change) -> Verdict:
    roles = list(v.roles) or change.config.reviewers_for(change.paths)
    diff = change.workspace.diff(change.base)
    files = {**change.workspace.seed(), "change.diff": diff}
    findings = []
    for role in roles:
        harness = change.config.harness(f"checker-{role}")
        record = change.runtime.turn(harness, instructions(change.config.root, f"checker-{role}"),
                                     f"{REVIEW.format(task=change.task)}\n\n{RESULT}", files)
        change.spend(record)
        result = change.runtime.result(record)
        if result.get("verdict") != "approve":
            findings.append(f"{role} ({harness}): {result.get('findings') or 'gave no verdict'}")
    return Verdict(not findings, 4, f"judges:{','.join(roles)}", "\n\n".join(findings))


# ── level 5: the human ─────────────────────────────────────────────────────────────────────────
def human(change: Change) -> Verdict:
    """The human approved exactly this commit: their latest review, on the head commit."""
    pr = change.pr
    mine = [r for r in change.gh.reviews(pr["number"]) if r["user"]["login"] == change.config.human]
    ok = bool(mine) and mine[-1]["state"] == "APPROVED" and mine[-1]["commit_id"] == pr["head"]["sha"]
    return Verdict(ok, 5, "human", "" if ok else f"waiting on @{change.config.human}")


def check(v: Verify, change: Change) -> Verdict:
    return {"command": command, "rule": rule, "live": live, "judge": judge}[v.kind](v, change)
