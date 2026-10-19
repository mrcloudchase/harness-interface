"""Every task Keeper runs, by name, and the kind of workflow job it needs: `gate` (checks and a
status), `write` (deterministic jobs that change the repository) or `agent` (anything that runs
an agent). Loops are every document in `.keeper/loops/`."""
from __future__ import annotations

import tempfile
import time

import jobs
import prompts
from loop import Loop, publish
from memory import Memory, Scratch
from workspace import Workspace

JOBS = {f.__name__: f for f in (jobs.merge, jobs.publish, jobs.nightly, jobs.revert, jobs.promote,
                                jobs.backport, jobs.labels, jobs.owners, jobs.status)}
PROMPTS = {f.__name__: f for f in (prompts.triage, prompts.plan, prompts.digest, prompts.answer,
                                   prompts.escalate, prompts.decide)}


def kind(config, task: str) -> str:
    if task == "gate":
        return "gate"
    if task in JOBS:
        return "write"
    if task in PROMPTS or task in config.loops:
        return "agent"
    raise KeyError(f"no task {task!r}")


def run(ctx, task: str, item: str = "") -> str:
    if task == "gate":
        return jobs.gate(ctx, int(item))
    if task in JOBS:
        return JOBS[task](ctx, item or None)
    if task in PROMPTS:
        return PROMPTS[task](ctx, item or None)
    return run_loop(ctx, task, item)


def loop_issue(ctx, name: str) -> int:
    """A scheduled loop works on an issue of its own, one a week, so it has memory like any task."""
    title = f"{name}: week of {time.strftime('%Y-%m-%d', time.gmtime(time.time() - time.gmtime().tm_wday * 86400))}"
    for issue in ctx.gh.issues(labels="keeper"):
        if issue["title"] == title:
            return issue["number"]
    return ctx.gh.create_issue(title, ctx.config.loops[name].goal, ["keeper", "task"])["number"]


def run_loop(ctx, name: str, item: str = "") -> str:
    c = ctx.config
    doc = c.loops[name]
    if not c.enabled(doc):
        return f"off: {doc.needs} is not set"
    n = int(item) if item else loop_issue(ctx, name)
    issue = ctx.gh.issue(n)
    memory = Memory.load(ctx.gh, n)
    allowed, why = ctx.governor.allow(opening_pr=doc.opens_pr)
    if not allowed:
        ctx.gh.comment(n, f"Keeper's `{name}` loop didn't start: {why}.")
        return f"blocked: {why}"
    start = ctx.workspace.start(f"keeper/{n}", c.work)
    since = ctx.workspace.merge_base(start, f"origin/{c.work}")
    outcome = Loop(ctx, doc, issue, memory, start, since).run()
    publish(ctx, doc, issue, memory, outcome)
    return f"{outcome.state}: {outcome.reason or outcome.title}"


def replay(ctx, count: int = 2) -> bool:
    """Evolve's check: rerun the last `count` accepted build tasks from where they started, with the
    loops and prompts as they are now. Passes if every one is accepted again for no more than it
    cost the first time."""
    done = []
    for issue in ctx.gh.issues(labels="keeper", state="closed"):
        state = Memory.load(ctx.gh, issue["number"]).state
        if state.loop == "build" and state.end == "success":
            done.append((issue, state.spent()))
        if len(done) == count:
            break
    if not done:
        return True                          # nothing to compare against yet
    then = now = 0.0
    for issue, cost in done:
        pr = next((p for p in ctx.gh.pulls(state="closed") if p["head"]["ref"] == f"keeper/{issue['number']}"), None)
        if not pr:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            ctx.workspace.git("worktree", "add", "-q", "--detach", tmp, pr["base"]["sha"])
            try:
                trial = type(ctx)(ctx.config, ctx.gh, Workspace(tmp), ctx.governor, ctx.runtime)
                outcome = Loop(trial, ctx.config.loops["build"], issue, Scratch(), pr["base"]["sha"], pr["base"]["sha"]).run()
            finally:
                ctx.workspace.git("worktree", "remove", "--force", tmp)
        if outcome.state != "success":
            print(f"#{issue['number']}: {outcome.state} on replay")
            return False
        then, now = then + cost, now + outcome.spent
        print(f"#{issue['number']}: accepted again for ${outcome.spent:.2f} (first time ${cost:.2f})")
    return now <= then
