"""Memory, the governor and the runtime client: state survives between runs on GitHub alone, the
brakes hold, and an agent's own files never become the project's."""
import pytest

from config import Config
from governor import Governor
from memory import Memory, State, parse, render, today
from runtime import HarnessError, Runtime
from workspace import Workspace


def test_state_round_trips_through_a_comment(gh):
    n = gh.create_issue("t", "", [])["number"]
    m = Memory.load(gh, n)
    m.record("resp_1", 0.25)
    m.record("resp_2", 0.5)
    again = Memory.load(gh, n).state
    assert again.responses == ["resp_1", "resp_2"] and again.spent() == 0.75 and again.spent(today()) == 0.75
    assert len(gh.comments(n)) == 1                              # one comment, edited in place
    assert parse("no state here") is None and parse(render(State(end="success"))).end == "success"


def test_the_same_failure_twice_is_no_progress(gh):
    m = Memory.load(gh, gh.create_issue("t", "", [])["number"])
    assert not m.failed("test_x failed: 1 != 2")
    assert m.failed("test_x  failed:\n1 != 2")                   # whitespace is not progress
    assert not m.failed("test_y failed")


def test_the_governor_holds(project, gh):
    c = Config.load(project)
    assert Governor(c, gh, enabled=False).allow() == (False, "Keeper is paused (KEEPER_ENABLED is not true)")
    assert Governor(c, gh, enabled=True).allow() == (True, "")
    assert not Governor(c, gh, enabled=True).allow(run_spent=5.0)[0]
    n = gh.create_issue("spent", "", ["keeper"])["number"]
    gh.comment(n, render(State(spend=[[today(), 39.5]])))
    ok, why = Governor(c, gh, enabled=True).allow(run_spent=0.6)
    assert not ok and "today's budget" in why
    for i in range(3):
        gh.create_pull(f"x{i}", f"keeper/{i}", "main", "")
    gh.comment(n, render(State()))
    gh.comments_[n] = gh.comments_[n][-1:]
    assert "already open" in Governor(c, gh, enabled=True).allow(opening_pr=True)[1]


def test_a_turns_own_files_are_never_the_projects(tmp_path, monkeypatch):
    rt = Runtime(tmp_path, sandboxed=True)
    rt._ready["claude-code"] = {"AGENTS.md"}
    monkeypatch.setattr(rt, "file", lambda rid, path: f"<{path}>".encode())
    record = {"id": "r", "harness": {"name": "claude-code", "files": ["src/a.py", "AGENTS.md", ".home/x", "keeper.json"],
                                     "deleted": ["old.py", ".hi/request.json"]}}
    assert rt.changes(record) == {"src/a.py": b"<src/a.py>", "old.py": None}


def test_a_sandboxed_runtime_refuses_a_local_turn(tmp_path, monkeypatch):
    rt = Runtime(tmp_path, sandboxed=True)
    rt._ready["h"] = set()
    monkeypatch.setattr(rt, "_call", lambda *a, **k: {"id": "r", "harness": {"runtime": "local"}})
    with pytest.raises(HarnessError, match="sandboxed"):
        rt.turn("h", "be good", "do it")
    assert Runtime(tmp_path, sandboxed=False).sandboxed is False


def test_project_code_never_sees_a_credential(project, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_secret")
    monkeypatch.setenv("KEEPER_SECRETS", '{"x": "y"}')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    ws = Workspace(project, token="ghs_secret", secrets={"ANTHROPIC_API_KEY": "sk-ant"})
    ok, out = ws.run("env")
    assert ok and "ghs_secret" not in out and "sk-ant" not in out and "KEEPER_SECRETS" not in out
    ok, out = ws.run("env", with_secrets=True)
    assert "ANTHROPIC_API_KEY=sk-ant" in out and "ghs_secret" not in out
    ws.git("config", "--local", "--list")
    assert "ghs" not in (project / ".git" / "config").read_text()      # the token never lands in the checkout
