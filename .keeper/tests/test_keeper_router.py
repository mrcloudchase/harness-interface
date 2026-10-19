"""Only the human's own actions start work; Keeper's steps arrive as dispatches; nobody else's
events start anything."""
from config import Config
from router import route

REPO = {"full_name": "o/r"}


def pr_event(action="opened", head_repo="o/r", sender="someone"):
    return {"action": action, "sender": {"login": sender}, "repository": REPO,
            "pull_request": {"number": 7, "head": {"repo": {"full_name": head_repo}}}}


def test_dispatches_and_schedules(project):
    c = Config.load(project)
    assert route(c, "workflow_dispatch", {"inputs": {"task": "gate", "item": "3"}}) == [("gate", "3")]
    assert route(c, "workflow_dispatch", {"inputs": {}}) == []
    assert route(c, "schedule", {"schedule": "0 3 * * *"}) == [("nightly", ""), ("status", "")]


def test_pull_requests_from_this_repository_are_gated(project):
    c = Config.load(project)
    assert route(c, "pull_request", pr_event()) == [("gate", "7")]
    assert route(c, "pull_request", pr_event(head_repo="fork/r")) == []
    assert route(c, "pull_request", pr_event(action="closed")) == []


def test_only_the_humans_actions_start_work(project):
    c = Config.load(project)
    issue = {"number": 4}
    for sender, expected in (("owner", [("triage", "4")]), ("stranger", [])):
        assert route(c, "issues", {"action": "opened", "sender": {"login": sender}, "issue": issue}) == expected
    assert route(c, "issues", {"action": "labeled", "sender": {"login": "owner"}, "issue": issue,
                               "label": {"name": "agent:ready"}}) == [("spec", "4")]
    comment = {"action": "created", "sender": {"login": "owner"}, "issue": issue, "comment": {"body": "@keeper why?"}}
    assert route(c, "issue_comment", comment) == [("answer", "4")]
    assert route(c, "issue_comment", {**comment, "sender": {"login": "stranger"}}) == []
    review = {"action": "submitted", "sender": {"login": "owner"}, "pull_request": {"number": 9}}
    assert route(c, "pull_request_review", review) == [("gate", "9")]


def test_a_push_sets_off_what_its_paths_need(project):
    c = Config.load(project)
    push = {"ref": "refs/heads/main", "sender": {"login": "owner"},
            "commits": [{"added": [], "modified": ["VISION.md", "keeper.toml", "CHANGELOG.md"], "removed": []}]}
    tasks = route(c, "push", push)
    assert ("labels", "") in tasks and ("plan", "") in tasks and ("owners", "") in tasks and ("status", "") in tasks
    assert ("release", "") not in tasks                  # the human's push starts the release workflow itself
    assert route(c, "push", {**push, "ref": "refs/heads/feature"}) == []
    assert route(c, "push", {**push, "sender": {"login": "stranger"}}) == []
