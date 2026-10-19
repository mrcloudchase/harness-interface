"""The deterministic tasks: rules written as code, no agent anywhere. Gate decides what may merge;
Merge, Release, Nightly, Revert, Backport, Promote, Labels, Owners and Status keep the project
moving and visible."""
from __future__ import annotations

import re

from config import Verify
from memory import Memory
from metrics import collect, render
from verifiers import Change, Verdict, command, human, rule

GATE_RULES = ("tests_only_grow", "size_budget", "commit_format", "themed", "verified")
BASE_LABELS = {
    "keeper": ("0e8a16", "Keeper works on this"), "agent:ready": ("1d76db", "Ready for an agent"),
    "needs-human": ("d93f0b", "Waiting on the human"), "human-tier": ("b60205", "Touches a path only the human approves"),
    "epic": ("5319e7", "A theme's work"), "task": ("c5def5", "One change"), "bug": ("ee0701", "Something is broken"),
    "regression": ("b60205", "Something that worked stopped working"), "flake": ("fbca04", "A test that fails sometimes"),
    "design": ("bfd4f2", "Merging it records a decision"), "revert": ("b60205", "Undoes a change"),
    "keeper-status": ("0e8a16", "Keeper's status board"),
}
STATUS_TITLE = "Keeper status"


def verdict_comment(gh, n: int, sha: str, why: str) -> None:
    gh.comment(n, f'{why}\n\n<!-- keeper:verdict {{"sha": "{sha}", "passed": true}} -->')


def is_keeper_head(config, pr: dict) -> bool:
    ref = pr["head"]["ref"]
    return ref.startswith("keeper/") or (ref == config.work and pr["base"]["ref"] == config.release != config.work)


# ── Gate ───────────────────────────────────────────────────────────────────────────────────────
def gate(ctx, n: int) -> str:
    """Checks, rules, and the human for human-tier paths. Sets `keeper/gate`; a Keeper PR that
    passes goes on to Merge."""
    gh, ws, c = ctx.gh, ctx.workspace, ctx.config
    pr = gh.pull(int(n))
    sha = pr["head"]["sha"]
    if pr["state"] != "open":
        return "closed"
    gh.set_status(sha, "pending", "Keeper is checking this commit")
    ws.fetch(pr["base"]["ref"])
    ws.checkout(f"pull/{pr['number']}/head")
    base = ws.merge_base("HEAD", f"origin/{pr['base']['ref']}")
    change = Change(c, ws, base, gh.pull_files(pr["number"]), pr=pr, gh=gh)
    checks = command(Verify("command", run="checks"), change)
    if not checks.passed and command(Verify("command", run="checks"), change).passed:
        flake(ctx, pr, checks.reasons)                       # failed, then passed: a flake, not this change
        checks = Verdict(True, 1, checks.name)
    verdicts = [checks, rule(Verify("rule", rules=GATE_RULES), change)]
    if failed := [v for v in verdicts if not v.passed]:
        gh.set_status(sha, "failure", failed[0].reasons.splitlines()[0])
        gh.comment(pr["number"], "Keeper's gate failed on " + sha[:12] + ":\n\n" +
                   "\n\n".join(f"**{v.name}**\n```\n{v.reasons[-3000:]}\n```" for v in failed))
        return "failure"
    if any(c.is_human_tier(p) for p in change.paths) and pr["user"]["login"] != c.human:
        if not (h := human(change)).passed:
            gh.set_status(sha, "pending", h.reasons)
            gh.add_labels(pr["number"], ["needs-human", "human-tier"])
            try:
                gh.request_review(pr["number"], c.human)
            except Exception:  # noqa: BLE001 — already requested, or not allowed: the label says it
                pass
            return "waiting"
    gh.set_status(sha, "success", "checks, rules and approvals pass")
    gh.remove_label(pr["number"], "needs-human")
    if is_keeper_head(c, pr):
        ctx.dispatch("merge", pr["number"])
    return "success"


def flake(ctx, pr: dict, reasons: str) -> None:
    title = f"flake: {reasons.splitlines()[0][:80]}"
    if not any(i["title"] == title for i in ctx.gh.issues(labels="flake")):
        issue = ctx.gh.create_issue(title, f"Failed, then passed, on #{pr['number']}:\n\n```\n{reasons[-3000:]}\n```",
                                    ["keeper", "flake", "agent:ready"])
        ctx.dispatch("flake", issue["number"])


# ── Merge and what follows ─────────────────────────────────────────────────────────────────────
TRAILERS = re.compile(r"^(Closes #\d+|(Theme|Keeper-Loop|Fixes|Cc|Regression|Reverts): .+)$", re.M)


def merge(ctx, n: int) -> str:
    gh, c = ctx.gh, ctx.config
    pr = gh.pull(int(n))
    if pr["state"] != "open" or not is_keeper_head(c, pr) or gh.status(pr["head"]["sha"]) != "success":
        return "not ready"
    promote = pr["head"]["ref"] == c.work
    trailers = "\n".join(m.group(0) for m in TRAILERS.finditer(pr["body"] or ""))
    gh.merge(pr["number"], pr["head"]["sha"], f"{pr['title']} (#{pr['number']})",
             f"{trailers}\nReviewed-by: keeper/gate", "merge" if promote else "squash")
    for task, item in follow_ups(c, gh.pull_files(pr["number"]), pr["base"]["ref"], pr, by_keeper=True):
        ctx.dispatch(task, item)
    return "merged"


def follow_ups(config, paths, branch: str, pr: dict | None = None, by_keeper: bool = False) -> list[tuple[str, str]]:
    """The tasks a change to `branch` sets off. Keeper's own merges start no workflow, so they also
    dispatch the release; a human's push starts it already."""
    tasks: list[tuple[str, str]] = []
    if "VISION.md" in paths:
        tasks += [("labels", ""), ("plan", "")]
    if "keeper.toml" in paths:
        tasks.append(("owners", ""))
    if by_keeper and branch == config.release and "CHANGELOG.md" in paths:
        tasks.append(("release", ""))
    if pr:
        labels = {label["name"] for label in pr.get("labels", [])}
        body = pr.get("body") or ""
        if "revert" in labels and (m := re.search(r"^Regression: #(\d+)", body, re.M)):
            tasks.append(("repair", m.group(1)))
        if config.rigor.get("stable_branch") and re.search(r"^Cc: stable", body, re.M):
            tasks.append(("backport", str(pr["number"])))
        if "design" in labels:
            tasks.append(("decide", str(pr["number"])))
    tasks.append(("status", ""))
    return tasks


def release(ctx, _=None) -> str:
    """The project's release workflow, started on the release branch: it tags the newest changelog
    section if it isn't tagged yet."""
    ctx.gh.dispatch("", "", ref=ctx.config.release, workflow="release.yml")
    return "dispatched"


# ── Nightly, Revert, Promote, Backport ─────────────────────────────────────────────────────────
def status_memory(ctx) -> Memory:
    return Memory.load(ctx.gh, status_issue(ctx))


def nightly(ctx, _=None) -> str:
    """The live run on the work branch: a green run counts toward promotion, a red one is reverted."""
    c, ws = ctx.config, ctx.workspace
    if not c.live.get("command"):
        return "no live command"
    ws.checkout(c.work)
    sha = ws.head()
    ok, out = ws.run(c.live["command"], with_secrets=True)
    memory = status_memory(ctx)
    data = memory.state.data
    if ok:
        if data.get("last_green") != sha:                    # a re-run of the same commit is not another day
            data["streak"] = data.get("streak", 0) + 1
        data["last_green"] = sha
        memory.save()
        if c.work != c.release and data["streak"] >= c.soak:
            ctx.dispatch("promote")
        return "green"
    data["streak"] = 0
    memory.save()
    good = data.get("last_green", "")
    title = f"regression: nightly fails on {sha[:12]}"
    if any(i["title"] == title for i in ctx.gh.issues(labels="regression")):
        return "red, already filed"
    body = (f"The nightly live run fails on `{sha}`; it last passed on `{good or 'never'}`.\n\n"
            f"```\n{out[-3000:]}\n```\n\nBad: {sha}\nGood: {good}\n")
    labels = ["keeper", "regression"] + ([] if good else ["needs-human"])
    issue = ctx.gh.create_issue(title, body, labels)
    if good:
        ctx.dispatch("revert", issue["number"])
    return "red"


def revert(ctx, n: int) -> str:
    """Find the change that broke the live run, and open a PR that reverts it."""
    gh, ws, c = ctx.gh, ctx.workspace, ctx.config
    issue = gh.issue(int(n))
    bad, good = (re.search(rf"^{k}: (\w+)", issue["body"], re.M).group(1) for k in ("Bad", "Good"))
    ws.checkout(c.work)
    commits = ws.commits(good, bad)
    culprit = commits[0] if len(commits) == 1 else ws.bisect(good, bad, c.live["command"])
    subject = ws.git("log", "-1", "--format=%s", culprit)
    diff = ws.git("show", "--format=", culprit)
    gh.edit_issue(issue["number"], body=f"{issue['body']}\n\n## The change that broke it: `{culprit}` {subject}\n\n"
                                        f"```diff\n{diff[:20000]}\n```\n\nRe-land it with a fix.")
    branch = f"keeper/revert-{culprit[:12]}"
    ws.start(branch, c.work)
    ws.revert(culprit)
    ws.push(branch)
    pr = gh.create_pull(f"revert: {subject}"[:120], branch, c.work,
                        f"Reverts {culprit}, which broke the nightly live run.\n\nRegression: #{issue['number']}\n"
                        f"Theme: regression\nReverts: {culprit}\n")
    gh.add_labels(pr["number"], ["keeper", "revert"])
    verdict_comment(gh, pr["number"], ws.head(), f"Reverting {culprit[:12]} restores the last green state.")
    gh.add_labels(issue["number"], ["agent:ready"])
    ctx.dispatch("gate", pr["number"])
    return f"reverting {culprit[:12]}"


def promote(ctx, _=None) -> str:
    """After `soak` green nightlies, the work branch goes to the release branch."""
    gh, c = ctx.gh, ctx.config
    if c.work == c.release:
        return "one branch"
    open_ = [p for p in gh.pulls() if p["head"]["ref"] == c.work and p["base"]["ref"] == c.release]
    pr = open_[0] if open_ else gh.create_pull(f"promote: {c.work} to {c.release}", c.work, c.release,
                                               f"{c.work} passed {c.soak} nightly live runs in a row.\n\nTheme: release\n")
    gh.add_labels(pr["number"], ["keeper"])
    verdict_comment(gh, pr["number"], gh.pull(pr["number"])["head"]["sha"], f"{c.soak} green nightlies in a row.")
    ctx.dispatch("gate", pr["number"])
    return f"promoting #{pr['number']}"


def backport(ctx, n: int) -> str:
    gh, ws, c = ctx.gh, ctx.workspace, ctx.config
    stable = c.rigor.get("stable_branch")
    pr = gh.pull(int(n))
    if not stable or not pr.get("merge_commit_sha"):
        return "nothing to backport"
    branch = f"keeper/backport-{pr['number']}"
    ws.start(branch, stable)
    ws.fetch(pr["merge_commit_sha"])
    ws.git("cherry-pick", "-x", pr["merge_commit_sha"])
    ws.push(branch)
    new = gh.create_pull(f"{pr['title']} [{stable}]"[:120], branch, stable,
                         f"Backports #{pr['number']}.\n\nTheme: stable\n")
    gh.add_labels(new["number"], ["keeper"])
    verdict_comment(gh, new["number"], ws.head(), f"A clean cherry-pick of #{pr['number']}.")
    ctx.dispatch("gate", new["number"])
    return f"backport #{new['number']}"


# ── Labels, Owners, Status ─────────────────────────────────────────────────────────────────────
THEME = re.compile(r"^\d+\.\s+\*\*(.+?)\*\*", re.M)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def themes(root) -> list[str]:
    """The ranked themes in VISION.md: `1. **Theme name**: what done looks like`."""
    text = (root / "VISION.md").read_text() if (root / "VISION.md").is_file() else ""
    section = text.split("## Themes", 1)[-1].split("\n## ", 1)[0] if "## Themes" in text else ""
    return [slug(t) for t in THEME.findall(section)]


def labels(ctx, _=None) -> str:
    have = {label["name"] for label in ctx.gh.labels()}
    wanted = {**BASE_LABELS, **{f"theme:{t}": ("fef2c0", "A theme in VISION.md") for t in themes(ctx.config.root)}}
    for name, (color, description) in wanted.items():
        if name not in have:
            ctx.gh.create_label(name, color, description)
    return f"{len(wanted)} labels"


def codeowners(config) -> str:
    def owner_path(pattern: str) -> str:                   # `dir/*` in keeper.toml is everything under dir/
        return "/" + (pattern.rstrip("*") if pattern.endswith("/*") or pattern.endswith("/**") else pattern)
    lines = [f"{owner_path(p)} @{config.human}" for p in config.human_tier]
    return "# Generated from keeper.toml's [tiers] by Keeper's Owners job. Edit keeper.toml, not this.\n" + "\n".join(lines) + "\n"


def owners(ctx, _=None) -> str:
    gh, ws, c = ctx.gh, ctx.workspace, ctx.config
    ws.start("keeper/owners", c.work)
    path = c.root / ".github" / "CODEOWNERS"
    if path.is_file() and path.read_text() == codeowners(c):
        return "up to date"
    path.parent.mkdir(exist_ok=True)
    path.write_text(codeowners(c))
    sha = ws.commit("owners: regenerate CODEOWNERS from keeper.toml")
    ws.push("keeper/owners")
    pr = gh.create_pull("owners: regenerate CODEOWNERS from keeper.toml", "keeper/owners", c.work,
                        "keeper.toml's human tier changed.\n\nTheme: keeper\n")
    gh.add_labels(pr["number"], ["keeper"])
    verdict_comment(gh, pr["number"], sha, "Generated from keeper.toml.")
    ctx.dispatch("gate", pr["number"])
    return f"#{pr['number']}"


def status_issue(ctx) -> int:
    found = ctx.gh.issues(labels="keeper-status")
    if found:
        return found[0]["number"]
    issue = ctx.gh.create_issue(STATUS_TITLE, "Keeper keeps this up to date.", ["keeper-status", "keeper"])
    try:
        ctx.gh.pin(issue["node_id"])
    except Exception:  # noqa: BLE001 — pinning is a nicety; the label finds it
        pass
    return issue["number"]


def status(ctx, _=None) -> str:
    n = status_issue(ctx)
    body = f"# {STATUS_TITLE}\n\nThe always-current view. The weekly digest has the story.\n\n{render(collect(ctx.gh), ctx.config.budget)}"
    ctx.gh.edit_issue(n, body=body)
    return f"#{n}"
