"""The one-shot agent tasks: one judgment each, written to GitHub. Triage, Plan, Digest, Answer,
Escalate and Decide. Each asks one role one question, reads its keeper.json, and acts."""
from __future__ import annotations

import json
import time

from jobs import status_issue, themes
from memory import Memory
from metrics import collect, render
from roles import RESULT, instructions
from runtime import answer as said, cost

MAX_NEW_TASKS = 6                            # what one Plan run may add
TEXT = "Reply with the finished text only: it is posted exactly as you write it. Write no files."


def ask(ctx, role: str, item: int, text: str, files: dict[str, str] | None = None,
        structured: bool = True) -> tuple[str, dict]:
    """One turn of `role`; its spend is recorded on `item`. Returns its answer and, when
    `structured`, its keeper.json."""
    record = ctx.runtime.turn(ctx.config.harness(role), instructions(ctx.config.root, role),
                              f"{text}\n\n{RESULT if structured else TEXT}", {**ctx.workspace.seed(), **(files or {})})
    Memory.load(ctx.gh, item).record(record["id"], cost(record))
    return said(record), ctx.runtime.result(record)


def thread(gh, n: int, last: int = 20) -> str:
    """An issue or pull request as Keeper knows it: its text, its conversation, and Keeper's record of
    the work on it: loop, end state, attempts and spend."""
    issue = gh.issue(n)
    comments = [c for c in gh.comments(n) if "keeper:state" not in c["body"]][-last:]
    s = Memory.load(gh, n).state
    record = (f"\n\nKeeper's record: loop `{s.loop or '—'}`, end `{s.end or '—'}`, {s.attempts} maker turns, "
              f"${s.spent():.2f} spent, branch `{s.branch or '—'}`.") if s.responses else ""
    linked = [p for p in gh.pulls(state="all") if f"Closes #{n}" in (p.get("body") or "")]
    prs = "".join(f"\nPull request #{p['number']} {p['title']} ({'merged' if p.get('merged_at') else p['state']})" for p in linked)
    return f"# #{n} {issue['title']}\n\n{issue.get('body') or ''}{record}{prs}\n\n" + "\n\n".join(
        f"**@{c['user']['login']}**: {c['body']}" for c in comments)


# ── Triage ─────────────────────────────────────────────────────────────────────────────────────
def triage(ctx, n: int) -> str:
    gh = ctx.gh
    allowed = themes(ctx.config.root)
    _, r = ask(ctx, "writer", int(n), f"""Triage this issue for the project.

Write keeper.json: {{"type": "task" | "bug" | "epic", "theme": one of {json.dumps(allowed)} or "",
"ready": true if an agent can do it now with checkable acceptance criteria,
"questions": "what must be clarified first, if not ready"}}

{thread(gh, int(n))}""")
    labels = ["keeper", r.get("type") if r.get("type") in ("task", "bug", "epic") else "task"]
    if r.get("theme") in allowed:
        labels.append(f"theme:{r['theme']}")
    if r.get("ready") and r.get("type") != "epic":
        gh.add_labels(int(n), [*labels, "agent:ready"])
        ctx.dispatch("spec", n)
        return "ready"
    gh.add_labels(int(n), [*labels, *(["needs-human"] if r.get("questions") else [])])
    if r.get("questions"):
        gh.comment(int(n), f"Before an agent can start:\n\n{r['questions']}")
    return "waiting"


# ── Plan ───────────────────────────────────────────────────────────────────────────────────────
def plan(ctx, _=None) -> str:
    gh = ctx.gh
    status = status_issue(ctx)
    open_ = [{"number": i["number"], "title": i["title"], "labels": [label["name"] for label in i["labels"]]}
             for i in gh.issues()]
    _, r = ask(ctx, "planner", status, f"""Plan the project's next work from VISION.md: its themes, in
rank order, against what is already open (open-issues.json) and the code. Add only what is missing;
each task must be one change an agent can finish, with acceptance criteria a test can check.
Where the vision is ambiguous or a change needs a human-tier path, ask instead, as an RFC.

Write keeper.json: {{"epics": [{{"theme": "<slug>", "title": "...", "body": "...",
"tasks": [{{"title": "<area>: <summary>", "body": "what and why, then ## Acceptance criteria"}}]}}],
"rfcs": [{{"title": "...", "body": "the question, the options, your recommendation"}}]}}

Themes: {json.dumps(themes(ctx.config.root))}""", {"open-issues.json": json.dumps(open_, indent=1)})
    titles = {i["title"]: i for i in gh.issues()}
    added = 0
    for epic in r.get("epics", []):
        t = epic.get("theme", "")
        theme_label = [f"theme:{t}"] if t in themes(ctx.config.root) else []
        parent = titles.get(epic["title"]) or gh.create_issue(epic["title"], epic.get("body", ""), ["keeper", "epic", *theme_label])
        for task in epic.get("tasks", []):
            if added >= MAX_NEW_TASKS or task["title"] in titles:
                continue
            child = gh.create_issue(task["title"], task.get("body", ""), ["keeper", "task", *theme_label])
            gh.add_sub_issue(parent["number"], child["id"])
            titles[task["title"]] = child
            added += 1
            ctx.dispatch("triage", child["number"])
    for rfc in r.get("rfcs", []):
        if rfc["title"] not in titles:
            gh.create_issue(rfc["title"], rfc.get("body", ""), ["keeper", "rfc", "needs-human"])
    return f"{added} tasks"


# ── Digest ─────────────────────────────────────────────────────────────────────────────────────
def digest(ctx, _=None) -> str:
    gh = ctx.gh
    week = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7 * 86400))
    merged = [{"number": p["number"], "title": p["title"], "labels": [label["name"] for label in p["labels"]],
               "merged_at": p["merged_at"]} for p in gh.pulls(state="closed") if (p.get("merged_at") or "") >= week]
    data = render(collect(gh), ctx.config.budget)
    text, _ = ask(ctx, "writer", status_issue(ctx), f"""Write this week's digest for the project's one
human, who reads it instead of following along. Sections, in order: Shipped, by theme; Decisions made;
Waiting on you; Health; Cost; Next. Link every item (#n). Be brief and exact; say plainly what went wrong.

## Merged this week
{json.dumps(merged, indent=1)}

## Metrics
{data}""", structured=False)
    url = gh.post("Announcements", f"Keeper digest, week of {time.strftime('%Y-%m-%d', time.gmtime())}", text)
    return url


# ── Answer, Escalate, Decide ───────────────────────────────────────────────────────────────────
def answer(ctx, n: int) -> str:
    text, _ = ask(ctx, "writer", int(n), f"""The project's human asked you (@keeper) something in this
thread. Answer their latest question exactly, from Keeper's record and the project, citing issues,
PRs, commits and files.

{thread(ctx.gh, int(n))}

## The project now
{render(collect(ctx.gh), ctx.config.budget)}""", structured=False)
    ctx.gh.comment(int(n), text or "I couldn't find an answer; see the run's log.")
    return "answered"


def escalate(ctx, n: int) -> str:
    gh = ctx.gh
    state = Memory.load(gh, int(n)).state
    text, _ = ask(ctx, "writer", int(n), f"""Keeper's `{state.loop}` loop ended **{state.end}** on this
issue and needs the human. In under 200 words: the question they must answer, the options, your
recommendation, and links to the evidence.

{thread(gh, int(n))}""", structured=False)
    gh.comment(int(n), text)
    gh.add_labels(int(n), ["needs-human"])
    gh.remove_label(int(n), "agent:ready")
    return "escalated"


def decide(ctx, n: int) -> str:
    gh = ctx.gh
    pr = gh.pull(int(n))
    text, _ = ask(ctx, "writer", int(n), f"""Write the decision record for this merged change: Context,
Decision, Consequences, Alternatives considered. Under 300 words.

# #{pr['number']} {pr['title']}

{pr.get('body') or ''}

Files: {', '.join(gh.pull_files(int(n)))}""", structured=False)
    return gh.post("Decisions", f"Decision: {pr['title']} (#{pr['number']})", text)
