"""The deterministic jobs: the Gate decides what may merge, and nothing merges without it; Merge,
Nightly, Revert, Promote, Labels, Owners and Status do exactly their one job."""
import jobs
from conftest import make_ctx
from fakes import git


def proposed(project, gh, files: dict[str, str], head="keeper/5", title="src: change", body="Theme: fast-tests\n",
             user="github-actions[bot]", verified=True) -> dict:
    """A pull request whose head is on origin as refs/pull/N/head, the way GitHub keeps it."""
    git(project, "checkout", "-q", "-b", f"work-{len(gh.items)}")
    for path, text in files.items():
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text(text)
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", title)
    sha = git(project, "rev-parse", "HEAD")
    pr = gh.create_pull(title, head, "main", body, sha=sha, user=user)
    gh.files_[pr["number"]] = sorted(files)
    git(project, "push", "-q", "origin", f"HEAD:refs/pull/{pr['number']}/head")
    git(project, "checkout", "-q", "main")
    if verified:
        jobs.verdict_comment(gh, pr["number"], sha, "verified")
    return pr


def test_a_good_keeper_pr_passes_and_goes_to_merge(project, gh):
    pr = proposed(project, gh, {"src/extra.py": "x = 1\n"})
    assert jobs.gate(make_ctx(project, gh), pr["number"]) == "success"
    assert gh.status(pr["head"]["sha"]) == "success" and ("merge", str(pr["number"])) in gh.dispatched


def test_failures_are_reported_and_stop_it(project, gh):
    pr = proposed(project, gh, {"broken.txt": "x"})
    assert jobs.gate(make_ctx(project, gh), pr["number"]) == "failure"
    assert gh.status(pr["head"]["sha"]) == "failure" and not any(t == "merge" for t, _ in gh.dispatched)
    assert "sh check.sh" in gh.comments(pr["number"])[-1]["body"]
    for i, bad in enumerate((dict(verified=False), dict(title="no area here"), dict(body=""))):
        pr = proposed(project, gh, {f"src/ok{i}.py": "x = 1\n"}, **bad)
        assert jobs.gate(make_ctx(project, gh), pr["number"]) == "failure", bad


def test_human_tier_waits_for_the_human_on_this_commit(project, gh):
    pr = proposed(project, gh, {"core/engine.py": "x = 1\n"})
    ctx = make_ctx(project, gh)
    assert jobs.gate(ctx, pr["number"]) == "waiting"
    assert gh.status(pr["head"]["sha"]) == "pending" and gh.has_label(pr["number"], "needs-human")
    assert gh.requested == ["owner"]
    gh.review(pr["number"], "owner", "APPROVED", pr["head"]["sha"])
    assert jobs.gate(ctx, pr["number"]) == "success" and not gh.has_label(pr["number"], "needs-human")


def test_the_humans_own_pr_needs_no_approval_and_is_not_merged_by_keeper(project, gh):
    pr = proposed(project, gh, {"core/engine.py": "x = 1\n"}, head="owner-branch", user="owner", verified=False)
    assert jobs.gate(make_ctx(project, gh), pr["number"]) == "success"
    assert not any(t == "merge" for t, _ in gh.dispatched)


def test_a_flake_passes_and_is_filed(project, gh):
    (project / "check.sh").write_text('if [ -f once ]; then exit 0; fi; touch once; exit 1\n')
    git(project, "commit", "-qam", "flaky check")
    git(project, "push", "-q", "origin", "main")
    pr = proposed(project, gh, {"src/a.py": "x = 1\n"})
    assert jobs.gate(make_ctx(project, gh), pr["number"]) == "success"
    flakes = gh.issues(labels="flake")
    assert len(flakes) == 1 and ("flake", str(flakes[0]["number"])) in gh.dispatched


def test_merge_only_after_the_gate_and_then_its_follow_ups(project, gh):
    pr = proposed(project, gh, {"VISION.md": "v2", "CHANGELOG.md": "## [9.9.9]"}, body="Closes #2\nTheme: fast-tests\nnoise\n")
    ctx = make_ctx(project, gh)
    assert jobs.merge(ctx, pr["number"]) == "not ready"
    gh.set_status(pr["head"]["sha"], "success", "ok")
    assert jobs.merge(ctx, pr["number"]) == "merged"
    m = gh.merged[0]
    assert m["method"] == "squash" and "Closes #2" in m["message"] and "Theme: fast-tests" in m["message"] and "noise" not in m["message"]
    assert {"labels", "plan", "status"} <= {t for t, _ in gh.dispatched} and ("publish", "release.yml") in gh.dispatched
    assert jobs.publish(ctx, "release.yml") == "dispatched release.yml" and gh.workflows == ["release.yml"]


def test_follow_ups(project, gh):
    c = make_ctx(project, gh).config
    pr = {"number": 3, "labels": [{"name": "revert"}, {"name": "design"}], "body": "Regression: #8\nCc: stable\n"}
    tasks = jobs.follow_ups(c, ["src/a.py"], "main", pr, by_keeper=True)
    assert ("repair", "8") in tasks and ("decide", "3") in tasks and ("backport", "3") not in tasks
    assert jobs.follow_ups(c, ["keeper.toml"], "main") == [("owners", ""), ("status", "")]


def test_nightly_green_then_red_files_a_regression_and_reverts(project, gh):
    ctx = make_ctx(project, gh)
    assert jobs.nightly(ctx) == "green"
    git(project, "checkout", "-q", "main")                    # the job leaves the checkout on the commit it ran
    good = git(project, "rev-parse", "HEAD")
    (project / "live-broken.txt").write_text("x")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "src: break the live run")
    git(project, "push", "-q", "origin", "main")
    assert jobs.nightly(ctx) == "red"
    issue = gh.issues(labels="regression")[0]
    assert f"Good: {good}" in issue["body"] and ("revert", str(issue["number"])) in gh.dispatched
    assert jobs.nightly(ctx) == "red, already filed"
    assert jobs.revert(ctx, issue["number"]).startswith("reverting")
    pr = gh.pulls()[0]
    assert pr["title"] == "revert: src: break the live run" and f"Regression: #{issue['number']}" in pr["body"]
    assert gh.has_label(pr["number"], "revert") and ("gate", str(pr["number"])) in gh.dispatched
    assert "live-broken.txt" in gh.issue(issue["number"])["body"]                # the change, for the repair loop


def test_revert_bisects_when_several_changes_landed(project, gh):
    ctx = make_ctx(project, gh)
    good = git(project, "rev-parse", "HEAD")
    for name, broken in (("one", False), ("two", True), ("three", False)):
        (project / f"{name}.txt").write_text(name)
        if broken:
            (project / "live-broken.txt").write_text("x")
        git(project, "add", "-A")
        git(project, "commit", "-q", "-m", f"src: {name}")
    git(project, "push", "-q", "origin", "main")
    n = gh.create_issue("regression", f"Bad: {git(project, 'rev-parse', 'HEAD')}\nGood: {good}\n", ["regression"])["number"]
    jobs.revert(ctx, n)
    assert gh.pulls()[0]["title"] == "revert: src: two"


def test_promote_after_the_soak(project, gh):
    toml = (project / "keeper.toml").read_text().replace('work = "main"', 'work = "next"').replace("[branches]", "[branches]\nsoak = 2")
    (project / "keeper.toml").write_text(toml)
    git(project, "commit", "-qam", "keeper: soak on next")
    git(project, "push", "-q", "origin", "main")
    git(project, "push", "-q", "origin", "main:next")
    ctx = make_ctx(project, gh)
    jobs.nightly(ctx)
    assert ("promote", "") not in gh.dispatched
    git(project, "checkout", "-q", "main")
    (project / "src" / "b.py").write_text("y = 2\n")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "src: b")
    git(project, "push", "-q", "origin", "HEAD:next")
    jobs.nightly(ctx)
    assert ("promote", "") in gh.dispatched
    assert jobs.promote(ctx).startswith("promoting")
    pr = gh.pulls()[0]
    assert (pr["head"]["ref"], pr["base"]["ref"]) == ("next", "main") and jobs.is_keeper_head(ctx.config, pr)


def test_labels_owners_and_status(project, gh):
    ctx = make_ctx(project, gh)
    jobs.labels(ctx)
    assert {"theme:fast-tests", "theme:clear-errors", "agent:ready", "needs-human"} <= gh.label_names
    assert jobs.owners(ctx).startswith("#")
    pr = gh.pulls()[0]
    assert pr["head"]["ref"] == "keeper/owners" and "/core/ @owner" in git(project, "show", "keeper/owners:.github/CODEOWNERS")
    waiting = gh.create_issue("Decide something", "", ["needs-human"])
    jobs.status(ctx)
    jobs.status(ctx)
    board = gh.issues(labels="keeper-status")
    assert len(board) == 1 and f"#{waiting['number']} Decide something" in board[0]["body"]
