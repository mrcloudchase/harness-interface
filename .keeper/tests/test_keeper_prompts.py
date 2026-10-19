"""The one-shot agent tasks act on exactly what the agent answered, and count what it spent."""
import prompts
from conftest import make_ctx
from fakes import FakeRuntime
from memory import Memory


def answering(result=None, answer=""):
    return FakeRuntime(lambda n, h, t: {"result": result or {}, "answer": answer, "cost": 0.05})


def test_triage_labels_and_starts_the_spec(project, gh):
    n = gh.create_issue("Faster tests", "make them fast", [])["number"]
    ctx = make_ctx(project, gh, answering({"type": "task", "theme": "fast-tests", "ready": True}))
    assert prompts.triage(ctx, n) == "ready"
    assert all(gh.has_label(n, x) for x in ("keeper", "task", "theme:fast-tests", "agent:ready"))
    assert ("spec", str(n)) in gh.dispatched and Memory.load(gh, n).state.spent() == 0.05


def test_triage_asks_when_it_cannot_start(project, gh):
    n = gh.create_issue("Something", "", [])["number"]
    ctx = make_ctx(project, gh, answering({"type": "task", "theme": "invented", "ready": False, "questions": "Which part?"}))
    assert prompts.triage(ctx, n) == "waiting"
    assert gh.has_label(n, "needs-human") and not gh.has_label(n, "theme:invented") and "Which part?" in gh.comments(n)[-1]["body"]


def test_plan_adds_only_whats_missing_under_epics_and_asks_rfcs(project, gh):
    gh.create_issue("tests: already planned", "", ["task"])
    plan = {"epics": [{"theme": "fast-tests", "title": "Fast tests", "body": "",
                       "tasks": [{"title": "tests: already planned", "body": ""}] +
                                [{"title": f"tests: task {i}", "body": "## Acceptance criteria"} for i in range(9)]}],
            "rfcs": [{"title": "Should tests run in parallel?", "body": "options"}]}
    ctx = make_ctx(project, gh, answering(plan))
    assert prompts.plan(ctx) == f"{prompts.MAX_NEW_TASKS} tasks"
    epic = next(i for i in gh.issues() if i["title"] == "Fast tests")
    assert gh.has_label(epic["number"], "epic") and len(gh.sub_issues) == prompts.MAX_NEW_TASKS
    assert len([t for t, _ in gh.dispatched if t == "triage"]) == prompts.MAX_NEW_TASKS
    rfc = next(i for i in gh.issues() if i["title"].startswith("Should"))
    assert gh.has_label(rfc["number"], "needs-human")
    assert len([i for i in gh.issues() if i["title"] == "tests: already planned"]) == 1


def test_digest_answer_escalate_and_decide(project, gh):
    ctx = make_ctx(project, gh, answering(answer="All good this week. #1"))
    assert prompts.digest(ctx).startswith("https://")
    assert gh.posts[-1][0] == "Announcements" and gh.posts[-1][2] == "All good this week. #1"
    n = gh.create_issue("Question", "", [])["number"]
    gh.comment(n, "@keeper why is it slow?", user="owner")
    prompts.answer(ctx, n)
    assert gh.comments(n)[-1]["body"] == "All good this week. #1"
    gh.add_labels(n, ["agent:ready"])
    prompts.escalate(ctx, n)
    assert gh.has_label(n, "needs-human") and not gh.has_label(n, "agent:ready")
    pr = gh.create_pull("src: a decision", "keeper/9", "main", "why")
    prompts.decide(ctx, pr["number"])
    assert gh.posts[-1][0] == "Decisions"
