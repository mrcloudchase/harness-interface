"""A loop: agent turns on a task until its verifiers decide an end state. `Loop` runs; `publish`
puts the outcome on GitHub. A replay runs the same `Loop` and publishes nothing."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import LoopDoc
from roles import RESULT, instructions
from runtime import cost
from verifiers import Change, Verdict, check, no_workflows

SUCCESS, NO_OP, BLOCKED, STALLED, EXHAUSTED = "success", "no_op", "blocked", "stalled", "exhausted"
ORDER = {"command": 0, "rule": 1, "live": 2, "judge": 3}     # cheapest first; stop at the first failure


@dataclass
class Outcome:
    state: str
    reason: str = ""
    title: str = ""
    summary: str = ""
    verdicts: list[Verdict] = field(default_factory=list)
    spent: float = 0.0


def task_text(issue: dict) -> str:
    return f"# {issue['title']}\n\n{issue.get('body') or ''}".strip()


def theme(issue: dict) -> str:
    return next((label["name"][6:] for label in issue.get("labels", []) if label["name"].startswith("theme:")), "")


class Loop:
    def __init__(self, ctx, doc: LoopDoc, issue: dict, memory, start: str, since: str):
        """`start`: the commit each role starts from. `since`: what the change is measured against,
        the work branch it will land on."""
        self.ctx, self.doc, self.issue, self.memory = ctx, doc, issue, memory
        self.start, self.since = start, since

    def prompt(self, feedback: str) -> str:
        parts = [self.doc.goal.strip(), task_text(self.issue)]
        if feedback:
            parts.append(f"## What failed last time, verbatim\n\n{feedback}")
        parts.append(RESULT + ' Shape: {"title": "<area>: <summary>", "summary": "<what you changed and why>"}'
                     ' or {"no_op": "<why nothing needs to change>"}.')
        return "\n\n".join(parts)

    def verify(self, change: Change) -> list[Verdict]:
        verdicts = []
        for v in sorted(self.doc.verifiers, key=lambda v: ORDER[v.kind]):
            verdicts.append(check(v, change))
            if not verdicts[-1].passed:
                break
        return verdicts

    def run(self) -> Outcome:
        ctx, ws, memory = self.ctx, self.ctx.workspace, self.memory
        memory.state.loop = self.doc.name
        tries, last, feedback = self.doc.tries or ctx.config.budget.tries, STALLED, ""
        before = memory.state.spent()
        spent = lambda: round(memory.state.spent() - before, 4)    # this run's spend, judges included
        for role in self.doc.escalate:                       # the maker's work, on the next role's harness
            harness = ctx.config.harness(role)
            ws.reset(self.start)
            previous, feedback, memory.state.failure = None, "", ""      # a fresh start for a fresh harness
            for _ in range(tries):
                ok, why = ctx.governor.allow(spent())
                if not ok:
                    return Outcome(BLOCKED, why, spent=spent())
                record = ctx.runtime.turn(harness, instructions(ctx.config.root, self.doc.maker), self.prompt(feedback),
                                          files=None if previous else ws.seed(), previous=previous)
                previous = record["id"]
                memory.state.attempts += 1
                memory.record(record["id"], cost(record))
                ws.apply(ctx.runtime.changes(record))
                result = ctx.runtime.result(record)
                change = Change(ctx.config, ws, self.since, ws.changed(self.since), task_text(self.issue),
                                runtime=ctx.runtime, gh=ctx.gh,
                                spend=lambda r: memory.record(r["id"], cost(r)))
                if not change.paths and result.get("no_op"):
                    return Outcome(NO_OP, str(result["no_op"]), spent=spent())
                if bad := no_workflows(change):
                    verdicts = [Verdict(False, 2, "rules", bad)]
                else:
                    verdicts = self.verify(change)
                if all(v.passed for v in verdicts):
                    if not change.paths:
                        return Outcome(NO_OP, "the checks already pass", verdicts=verdicts, spent=spent())
                    title = str(result.get("title") or f"keeper: {self.issue['title']}")
                    return Outcome(SUCCESS, title=title if re.match(r"^[\w./-]+: \S", title) else f"keeper: {title}",
                                   summary=str(result.get("summary") or ""), verdicts=verdicts, spent=spent())
                feedback = "\n\n".join(f"[{v.name}] {v.reasons}" for v in verdicts if not v.passed)
                if memory.failed(feedback):
                    last = STALLED
                    break                                        # no progress: the next role takes over
                last = EXHAUSTED
        return Outcome(last, f"every role gave up; the last failure:\n\n{feedback}", spent=spent())


def publish(ctx, doc: LoopDoc, issue: dict, memory, outcome: Outcome) -> None:
    """The outcome on GitHub: the work pushed and, when the loop opens one, a pull request with the
    verdict the Gate requires; the end state on the issue; the next task dispatched."""
    gh, ws, n = ctx.gh, ctx.workspace, issue["number"]
    memory.state.end = outcome.state
    memory.state.branch = branch = f"keeper/{n}"
    memory.save(f"Keeper's `{doc.name}` loop ended **{outcome.state}**. {outcome.reason}".strip())
    for old in [x["name"] for x in issue.get("labels", []) if x["name"].startswith("end:")]:
        gh.remove_label(n, old)                              # one end state: the latest
    gh.add_labels(n, ["keeper", f"end:{outcome.state}"])
    if outcome.state == SUCCESS:
        sha = ws.commit(f"{outcome.title}\n\n{outcome.summary}\n\nCloses #{n}".strip())
        ws.push(branch)
        gh.remove_label(n, "agent:ready")
        if doc.opens_pr:
            pr = open_pr(ctx, doc, issue, branch, outcome, sha)
            ctx.dispatch("gate", pr)
    if outcome.state in (SUCCESS, NO_OP) and doc.then:
        ctx.dispatch(doc.then, n)
    elif outcome.state not in (SUCCESS, NO_OP):
        ctx.dispatch("escalate", n)


def open_pr(ctx, doc: LoopDoc, issue: dict, branch: str, outcome: Outcome, sha: str) -> int:
    gh, n = ctx.gh, issue["number"]
    checks = "\n".join(f"- {'✓' if v.passed else '✗'} level {v.level} · {v.name}" for v in outcome.verdicts)
    body = (f"{outcome.summary}\n\n## Verified\n{checks}\n\nCloses #{n}\n"
            f"Theme: {theme(issue) or 'none'}\nKeeper-Loop: {doc.name}\n")
    existing = [p for p in gh.pulls() if p["head"]["ref"] == branch]
    pr = existing[0]["number"] if existing else gh.create_pull(outcome.title, branch, ctx.config.work, body)["number"]
    gh.add_labels(pr, ["keeper", *[f"theme:{t}" for t in [theme(issue)] if t]])
    gh.comment(pr, f'Verified by Keeper on {sha[:12]}.\n\n<!-- keeper:verdict {{"sha": "{sha}", "passed": true}} -->')
    return pr
