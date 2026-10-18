"""Layer 2: a workspace tracks every change, reads any file as any snapshot left it, never steps
outside itself, and never exposes its internal paths."""
import os
import subprocess

import pytest

from harness_interface.errors import Invalid
from harness_interface.workspace import Workspace, require_git


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.init()
    return w


def test_init_twice_is_init_once(ws):
    base = ws.snapshot("first")
    ws.init()
    assert ws.snapshot("second") != base and (ws.path / ".hi").is_dir()


def test_paths_cannot_escape(ws, tmp_path):
    (tmp_path / "outside").mkdir()
    os.symlink(tmp_path / "outside", ws.path / "link")
    for rel in ("../x", "/etc/passwd", "link/x", "a/../../x"):
        with pytest.raises(Invalid):
            ws.write(rel, "nope")
        with pytest.raises(Invalid):
            ws.read(rel)
    ws.write("a/b/c.txt", "fine")
    assert (ws.path / "a/b/c.txt").read_text() == "fine"


def test_changes_since_a_snapshot(ws):
    ws.write("keep.txt", "1")
    ws.write("gone.txt", "1")
    ws.snapshot("base")
    ws.write("keep.txt", "2")
    ws.write("new.txt", "n")
    (ws.path / "gone.txt").unlink()
    for internal in (".hi/request.json", ".home/auth.json", "pkg/__pycache__/m.pyc"):
        ws.write(internal, "internal")
    assert ws.changes() == (["keep.txt", "new.txt"], ["gone.txt"])


def test_internal_paths_stay_internal_whatever_the_gitignore_says(ws):
    base = ws.snapshot("base")
    ws.write(".gitignore", "build/\n")              # the project's own, replacing anything
    ws.write(".home/auth.json", "secret")
    ws.write("app.py", "code")
    commit = ws.snapshot("turn")
    assert ws.changes() == ([], [])
    diff = ws.diff(base, commit)
    assert "app.py" in diff and "secret" not in diff and ".home" not in diff
    assert ".home/auth.json" not in ws.files(commit) and ".home/auth.json" not in ws.files()
    assert ws.read(".home/auth.json") is None and ws.read(".home/auth.json", commit) is None
    assert ws.read(".hi") is None and ws.read(".git/config") is None


def test_diff_between_snapshots_and_live(ws):
    ws.write("a.txt", "one\n")
    base = ws.snapshot("base")
    ws.write("a.txt", "two\n")
    live = ws.diff(base)                             # while something is still working
    assert "-one" in live and "+two" in live
    assert ws._git("diff", "--cached", "--name-only").stdout == ""   # its own index untouched
    head = ws.snapshot("head")
    assert ws.diff(base, head) == live


def test_files_and_reads_as_each_snapshot_left_them(ws):
    ws.write("a.txt", "one")
    ws.write("gone.txt", "x")
    first = ws.snapshot("first")
    ws.write("a.txt", "two")
    (ws.path / "gone.txt").unlink()
    second = ws.snapshot("second")
    assert ws.read("a.txt", first) == b"one" and ws.read("a.txt", second) == b"two" and ws.read("a.txt") == b"two"
    assert ws.read("gone.txt", first) == b"x" and ws.read("gone.txt", second) is None
    assert "gone.txt" in ws.files(first) and "gone.txt" not in ws.files(second)


def test_a_workspace_owned_by_someone_else_still_works(ws):
    if os.geteuid() != 0:
        pytest.skip("only root can give a directory away")
    ws.write("a.txt", "x")
    subprocess.run(["chown", "-R", "1000:1000", str(ws.path)], check=True)
    assert ws.snapshot("theirs") and ws.files() == ["a.txt"]


def test_no_git_is_said_up_front(monkeypatch):
    import harness_interface.workspace as w
    monkeypatch.setattr(w.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="git is required"):
        require_git()
