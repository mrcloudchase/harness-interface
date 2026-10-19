"""A loop ends in exactly one of its five states, for the reason it claims, and publishes only what
its verifiers allowed: success opens a verified PR and hands it to the Gate; anything else escalates."""
from conftest import make_ctx
from fakes import FakeRuntime, git
from memory import Memory, render, State
import tasks

FIX = {"files": {"src/app.py": "def add(a, b):\n    return a + b  # checked\n"},
       "result": {"title": "src: check add", "summary": "Checked it."}}
APPROVE = {"result": {"verdict": "approve"}}


def scripted(*maker_turns, judge=APPROVE):
    """Maker turns in order; every checker turn answers `judge`."""
    turns = iter(maker_turns)
    return FakeRuntime(lambda n, harness, text: judge if harness == "check-cli" and "Review this change" in text else next(turns))


def issue(gh, title="Check add", labels=("keeper", "task", "agent:ready", "theme:fast-tests")):
    return gh.create_issue(title, "## Acceptance criteria\n- add is checked", list(labels))["number"]


def test_success_opens_a_verified_pr_and_hands_it_to_the_gate(project, gh):
    n = issue(gh)
    rt = scripted(FIX)
    out = tasks.run_loop(make_ctx(project, gh, rt), "build", str(n))
    assert out.startswith("success")
    pr = gh.pulls()[0]
    assert pr["title"] == "src: check add" and pr["head"]["ref"] == f"keeper/{n}" and pr["base"]["ref"] == "main"
    assert f"Closes #{n}" in pr["body"] and "Theme: fast-tests" in pr["body"] and "Keeper-Loop: build" in pr["body"]
    assert any("keeper:verdict" in c["body"] for c in gh.comments(pr["number"]))
    assert ("gate", str(pr["number"])) in gh.dispatched
    assert git(project, "ls-remote", "--heads", "origin", f"keeper/{n}")          # the work is pushed
    assert gh.has_label(n, "end:success") and not gh.has_label(n, "agent:ready")
    state = Memory.load(gh, n).state
    assert (state.loop, state.end, state.attempts) == ("build", "success", 1) and state.spent() == 0.2  # maker + judge
    assert rt.turns[0]["seeded"] and "Keeper's maker" in rt.turns[0]["instructions"]


def test_feedback_then_success_within_one_conversation(project, gh):
    n = issue(gh)
    broken = {"files": {"broken.txt": "x"}}
    rt = scripted(broken, {"files": {"broken.txt": None, **FIX["files"]}, "result": FIX["result"]})
    assert tasks.run_loop(make_ctx(project, gh, rt), "build", str(n)).startswith("success")
    second = rt.turns[1]
    assert second["previous"] == "resp_0" and not second["seeded"] and "sh check.sh" in second["text"]


def test_no_progress_escalates_to_the_next_role_then_stalls(project, gh):
    n = issue(gh)
    broken = {"files": {"broken.txt": "x"}}
    rt = scripted(broken, broken, broken, broken)
    assert tasks.run_loop(make_ctx(project, gh, rt), "build", str(n)).startswith("stalled")
    assert [t["harness"] for t in rt.turns] == ["make-cli", "make-cli", "check-cli", "check-cli"]
    assert rt.turns[2]["seeded"]                                     # the next role starts fresh
    assert ("escalate", str(n)) in gh.dispatched and not gh.pulls()


def test_a_judge_can_send_it_back(project, gh):
    n = issue(gh)
    verdicts = iter([{"result": {"verdict": "changes", "findings": "src/app.py:2 says nothing"}}, APPROVE])
    makers = iter([FIX, {"files": {"src/app.py": "def add(a, b):\n    return a + b  # adds\n"}, "result": FIX["result"]}])
    rt = FakeRuntime(lambda n_, h, t: next(verdicts) if "Review this change" in t else next(makers))
    assert tasks.run_loop(make_ctx(project, gh, rt), "build", str(n)).startswith("success")
    assert "src/app.py:2 says nothing" in rt.turns[2]["text"]


def test_no_op_and_already_done(project, gh):
    n = issue(gh)
    rt = scripted({"result": {"no_op": "add is already checked"}})
    assert tasks.run_loop(make_ctx(project, gh, rt), "build", str(n)).startswith("no_op")
    assert not gh.pulls() and gh.has_label(n, "end:no_op")


def test_workflows_are_never_the_agents(project, gh):
    n = issue(gh)
    hack = {"files": {".github/workflows/x.yml": "on: push\n"}}
    rt = scripted(hack, hack, hack, hack)
    tasks.run_loop(make_ctx(project, gh, rt), "build", str(n))
    assert "workflows are the human's" in rt.turns[1]["text"] and not gh.pulls()


def test_brakes(project, gh):
    n = issue(gh)
    assert tasks.run_loop(make_ctx(project, gh, scripted(), enabled=False), "build", str(n)).startswith("blocked")
    expensive = {"files": {"broken.txt": "x"}, "cost": 6.0}
    rt = scripted(expensive, expensive)
    assert tasks.run_loop(make_ctx(project, gh, rt), "build", str(n)).startswith("blocked")
    assert len(rt.turns) == 1                                        # the run budget stopped the second turn


def test_spec_writes_failing_tests_and_hands_over_to_build(project, gh):
    toml = (project / "keeper.toml").read_text().replace('test = "sh check.sh"', 'test = "python3 -m pytest -q tests"')
    (project / "keeper.toml").write_text(toml)
    n = issue(gh)
    failing = {"files": {"tests/test_checked.py": "from pathlib import Path\n\ndef test_checked():\n"
                                                    "    assert 'checked' in Path('src/app.py').read_text()\n"},
               "result": {"title": "tests: add is checked", "summary": "The test."}}
    assert tasks.run_loop(make_ctx(project, gh, scripted(failing)), "spec", str(n)).startswith("success")
    assert not gh.pulls() and ("build", str(n)) in gh.dispatched          # no PR: build continues on the branch
    rt = scripted(FIX)
    assert tasks.run_loop(make_ctx(project, gh, rt), "build", str(n)).startswith("success")
    assert "tests/test_checked.py" in git(project, "show", "--stat", f"keeper/{n}~1")


def test_a_loop_is_given_facts_its_sandbox_cannot_reach(project, gh):
    rt = scripted({"result": {"no_op": "everything is current"}})
    assert tasks.run_loop(make_ctx(project, gh, rt), "upgrade", "").startswith("no_op")
    assert "Facts from outside your sandbox" in rt.turns[0]["text"] and "left-pad pinned 1.0 latest 1.3" in rt.turns[0]["text"]
    rt = scripted({"result": {"no_op": "nothing to do"}})
    tasks.run_loop(make_ctx(project, gh, rt), "docs", "")
    assert "Facts from outside" not in rt.turns[0]["text"]                      # only a loop that names a context


def test_a_scheduled_loop_keeps_a_weekly_issue(project, gh):
    rt = scripted({"result": {"no_op": "docs match"}})
    tasks.run_loop(make_ctx(project, gh, rt), "docs", "")
    tasks.run_loop(make_ctx(project, gh, scripted({"result": {"no_op": "still"}})), "docs", "")
    assert len([i for i in gh.issues() if i["title"].startswith("docs: week of")]) == 1
    assert tasks.run_loop(make_ctx(project, gh, rt), "strengthen", "").startswith("off")


def test_replay_accepts_only_cheaper_or_equal(project, gh):
    n = gh.create_issue("Check add", "", ["keeper", "task"])["number"]
    gh.items[n]["state"] = "closed"
    gh.comment(n, render(State(loop="build", end="success", spend=[["2099-01-01", 0.5]])))
    base = git(project, "rev-parse", "HEAD")
    pr = gh.create_pull("src: check add", f"keeper/{n}", "main", "")
    pr["state"], pr["base"]["sha"] = "closed", base
    assert tasks.replay(make_ctx(project, gh, scripted({**FIX, "cost": 0.1})))
    assert not tasks.replay(make_ctx(project, gh, scripted({**FIX, "cost": 0.9})))
    assert not tasks.replay(make_ctx(project, gh, scripted({"files": {"broken.txt": "x"}}, {"files": {"broken.txt": "x"}},
                                                          {"files": {"broken.txt": "x"}}, {"files": {"broken.txt": "x"}})))


def test_what_running_the_checks_leaves_behind_is_never_part_of_the_change(project, gh):
    (project / "check.sh").write_text("mkdir -p __pycache__ .pytest_cache && touch __pycache__/x.pyc .pytest_cache/v\n")
    git(project, "commit", "-qam", "checks that leave things behind")
    git(project, "push", "-q", "origin", "main")
    n = issue(gh)
    assert tasks.run_loop(make_ctx(project, gh, scripted(FIX)), "build", str(n)).startswith("success")
    assert git(project, "show", "--name-only", "--format=", f"keeper/{n}") == "src/app.py"


def test_an_item_shows_only_its_latest_end_state(project, gh):
    n = issue(gh)
    tasks.run_loop(make_ctx(project, gh, scripted({"result": {"no_op": "done"}})), "build", str(n))
    gh.add_labels(n, ["agent:ready"])
    tasks.run_loop(make_ctx(project, gh, scripted(FIX)), "build", str(n))
    assert gh.has_label(n, "end:success") and not gh.has_label(n, "end:no_op")
