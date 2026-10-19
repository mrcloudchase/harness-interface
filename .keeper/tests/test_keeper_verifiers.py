"""The ladder: commands, rules, judges and the human each decide exactly what they claim."""
from config import Config, Verify
from fakes import FakeRuntime, git
from verifiers import RULES, Change, check, command, human
from workspace import Workspace


def change(project, gh=None, pr=None, runtime=None):
    ws = Workspace(project)
    base = ws.head()
    return Change(Config.load(project), ws, base, [], task="# a task", pr=pr, gh=gh, runtime=runtime)


def touch(c: Change, path: str, text: str | None) -> None:
    p = c.workspace.root / path
    if text is None:
        p.unlink()
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    c.paths = c.workspace.changed(c.base)


def test_commands_pass_fail_expect_failure_and_repeat(project):
    c = change(project)
    assert command(Verify("command", run="checks"), c).passed
    touch(c, "broken.txt", "x")
    v = command(Verify("command", run="test"), c)
    assert not v.passed and "sh check.sh" in v.reasons
    assert command(Verify("command", run="test", expect="fail"), c).passed     # a new test that fails first
    (project / "count.sh").write_text('n=$(cat n 2>/dev/null || echo 0); echo $((n+1)) > n; [ "$n" -lt 2 ]\n')
    assert not command(Verify("command", run="sh count.sh", repeat=3), c).passed  # fails on the third run


def test_tests_only_grow(project):
    rule = RULES["tests_only_grow"]
    c = change(project)
    touch(c, "tests/test_app.py", "def test_add():\n    assert 1 + 1 == 2\n    assert True\n\ndef test_more():\n    assert 2\n")
    assert rule(c) == ""
    touch(c, "tests/test_app.py", "def test_add():\n    assert 1 + 1 == 2\n")
    assert "fewer assertions" in rule(c)
    touch(c, "tests/test_app.py", "def test_renamed():\n    assert 1\n    assert 2\n")
    assert "lost test_add" in rule(c)
    touch(c, "tests/test_app.py", None)
    assert "deleted" in rule(c)


def test_path_and_size_rules(project):
    c = change(project)
    touch(c, "tests/test_new.py", "def test_x():\n    assert 0\n")
    assert RULES["tests_only"](c) == ""
    touch(c, "src/app.py", "x = 1\n")
    assert "src/app.py" in RULES["tests_only"](c)
    assert RULES["size_decreased"](c) == ""                       # 2 lines down to 1
    touch(c, "src/big.py", "x = 1\n" * 60)
    assert "over the budget" in RULES["size_budget"](c) and RULES["size_decreased"](c)
    touch(c, ".github/workflows/x.yml", "on: push\n")
    assert "workflows" in RULES["no_workflows"](c)
    assert "loops and prompts" in RULES["keeper_paths"](c)


def test_pull_request_rules(project, gh):
    keeper = {"number": 0, "title": "src: add a thing", "body": "Theme: fast-tests",
              "head": {"ref": "keeper/3", "sha": "abc"}}
    pr = gh.create_pull(keeper["title"], "keeper/3", "main", keeper["body"], sha="abc")
    c = change(project, gh=gh, pr=pr)
    assert RULES["commit_format"](c) == "" and RULES["themed"](c) == ""
    assert "no verdict" in RULES["verified"](c)
    gh.comment(pr["number"], '<!-- keeper:verdict {"sha": "old", "passed": true} -->')
    assert "did not verify" in RULES["verified"](c)
    gh.comment(pr["number"], '<!-- keeper:verdict {"sha": "abc", "passed": true} -->')
    assert RULES["verified"](c) == ""
    pr["title"], pr["body"] = "Add a thing", ""
    assert RULES["commit_format"](c) and RULES["themed"](c)
    pr["head"]["ref"] = "someones-branch"                        # a human's PR needs no theme or verdict
    assert RULES["themed"](c) == "" and RULES["verified"](c) == ""


def test_the_human_must_approve_exactly_this_commit(project, gh):
    pr = gh.create_pull("core: x", "keeper/1", "main", "", sha="new")
    c = change(project, gh=gh, pr=pr)
    assert not human(c).passed
    gh.review(pr["number"], "owner", "APPROVED", "old")
    assert not human(c).passed
    gh.review(pr["number"], "someone", "APPROVED", "new")
    assert not human(c).passed
    gh.review(pr["number"], "owner", "APPROVED", "new")
    assert human(c).passed
    gh.review(pr["number"], "owner", "CHANGES_REQUESTED", "new")
    assert not human(c).passed


def test_judges_approve_or_say_why(project, gh):
    verdicts = iter([{"verdict": "approve"}, {"verdict": "changes", "findings": "src/app.py:1 is wrong"}, {}])
    rt = FakeRuntime(lambda n, h, t: {"result": next(verdicts)})
    c = change(project, gh=gh, runtime=rt)
    touch(c, "src/app.py", "x = 2\n")
    spent = []
    c.spend = spent.append
    assert check(Verify("judge"), c).passed
    v = check(Verify("judge", roles=("correctness", "security")), c)
    assert not v.passed and "src/app.py:1 is wrong" in v.reasons and "gave no verdict" in v.reasons
    assert len(spent) == 3 and rt.turns[0]["harness"] == "check-cli"
    assert "correctness reviewer" in rt.turns[0]["instructions"] and "Keep it simple" in rt.turns[0]["instructions"]
    git(project, "status")
