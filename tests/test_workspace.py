"""Layer 2: a workspace tracks every change, reads any file as any snapshot left it, byte for byte,
never steps outside itself, never exposes its internal paths, and keeps its history where nothing
that runs in it can reach; the reported artifacts under `.home/` are found by glob."""
import os
import subprocess

import pytest

from harness_interface.errors import Invalid
from harness_interface.workspace import Workspace, matcher, require_git


@pytest.fixture
def ws(tmp_path):
    w = Workspace(tmp_path / "ws")
    w.init()
    return w


def test_init_twice_is_init_once(ws):
    base = ws.snapshot("first")
    ws.init()
    assert ws.snapshot("second") != base


def test_its_history_lives_outside_it(ws):
    assert not (ws.path / ".git").exists() and ws.history.is_dir()
    assert not ws.history.is_relative_to(ws.path)


def test_nothing_written_inside_runs_when_the_server_snapshots(ws, tmp_path):
    """What runs in a workspace can write anything there, a project's own .git included; none of it
    is a hook or config of the history the server commits to."""
    proof = tmp_path / "ran"
    (ws.path / ".git" / "hooks").mkdir(parents=True)
    hook = ws.path / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\ntouch {proof}\n")
    hook.chmod(0o755)
    (ws.path / ".git" / "config").write_text(f"[core]\n\tfsmonitor = touch {proof}\n")
    ws.write(".gitattributes", "* filter=evil\n")
    ws.write("a.txt", "x")
    commit = ws.snapshot("after")
    assert not proof.exists()
    assert ws.files(commit) == [".gitattributes", "a.txt"]


def test_paths_cannot_escape(ws, tmp_path):
    (tmp_path / "outside").mkdir()
    os.symlink(tmp_path / "outside", ws.path / "link")
    for rel in ("../x", "/etc/passwd", "link/x", "a/../../x", ""):
        with pytest.raises(Invalid):
            ws.write(rel, "nope")
        with pytest.raises(Invalid):
            ws.read(rel)
        with pytest.raises(Invalid):
            ws.delete(rel)
    assert list((tmp_path / "outside").iterdir()) == []
    ws.write("a/b/c.txt", "fine")
    assert (ws.path / "a/b/c.txt").read_text() == "fine"


def test_delete_removes_a_link_never_what_it_points_at(ws, tmp_path):
    target = tmp_path / "precious"
    target.write_text("keep")
    os.symlink(target, ws.path / "link")
    ws.delete("link")
    ws.delete("never-there")
    assert target.read_text() == "keep" and not (ws.path / "link").is_symlink()


def test_writes_and_reads_are_byte_for_byte(ws):
    blob = bytes(range(256)) * 4
    ws.write("bin/data.bin", blob)
    ws.write("text.txt", "héllo\n")
    commit = ws.snapshot("bytes")
    assert ws.read("bin/data.bin") == blob and ws.read("bin/data.bin", commit) == blob
    assert ws.read("text.txt", commit) == "héllo\n".encode()


def test_changes_since_a_snapshot(ws):
    ws.write("keep.txt", "1")
    ws.write("gone.txt", "1")
    ws.snapshot("base")
    ws.write("keep.txt", "2")
    ws.write("new.txt", "n")
    ws.write("odd name ü.txt", "n")
    (ws.path / "gone.txt").unlink()
    for internal in (".home/auth.json", "pkg/__pycache__/m.pyc", ".git/config"):
        ws.write(internal, "internal")
    assert ws.changes() == (["keep.txt", "new.txt", "odd name ü.txt"], ["gone.txt"])


def test_changes_between_snapshots(ws):
    ws.write("a.txt", "1")
    ws.write("b.txt", "1")
    base = ws.snapshot("base")
    ws.write("a.txt", "2")
    (ws.path / "b.txt").unlink()
    ws.write("c.txt", "3")
    head = ws.snapshot("head")
    ws.write("later.txt", "not yet a part of head")
    assert ws.changes(base, head) == (["a.txt", "c.txt"], ["b.txt"])
    assert ws.changes(base) == (["a.txt", "c.txt", "later.txt"], ["b.txt"])


def test_internal_paths_stay_internal_whatever_the_gitignore_says(ws):
    base = ws.snapshot("base")
    ws.write(".gitignore", "build/\n")              # the project's own, replacing anything
    ws.write(".home/auth.json", "secret")
    ws.write(".git/HEAD", "ref: refs/heads/theirs\n")
    ws.write("app.py", "code")
    commit = ws.snapshot("turn")
    assert ws.changes() == ([], [])
    diff = ws.diff(base, commit)
    assert "app.py" in diff and "secret" not in diff and ".home" not in diff and "theirs" not in diff
    for files in (ws.files(commit), ws.files()):
        assert files == [".gitignore", "app.py"]
    assert ws.read(".home/auth.json") is None and ws.read(".home/auth.json", commit) is None
    assert ws.read(".git/HEAD") is None


def test_diff_between_snapshots_and_live(ws):
    ws.write("a.txt", "one\n")
    base = ws.snapshot("base")
    ws.write("a.txt", "two\n")
    live = ws.diff(base)                             # while something is still working
    assert "-one" in live and "+two" in live
    assert ws.changes() == (["a.txt"], [])           # the live diff staged nothing
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


def test_home_files_are_found_by_glob_and_read_byte_for_byte(ws):
    for rel in (".claude/projects/p1/memory/a.md", ".claude/projects/p1/memory/deep/b.md",
                ".claude/projects/p1/other.md", ".hermes/memories/m.bin", ".claude/settings.json"):
        ws.write(f".home/{rel}", rel)
    ws.write(".home/.hermes/memories/m.bin", b"\x00\xff")
    found = ws.home_files([".claude/projects/*/memory/**", ".hermes/memories/**"])
    assert sorted(found) == [".claude/projects/p1/memory/a.md", ".claude/projects/p1/memory/deep/b.md",
                             ".hermes/memories/m.bin"]
    assert ws.read_home(".hermes/memories/m.bin") == b"\x00\xff"
    assert ws.home_files([]) == {}
    before = found[".claude/projects/p1/memory/a.md"]
    ws.write(".home/.claude/projects/p1/memory/a.md", "changed")
    assert ws.home_files(["**/a.md"])[".claude/projects/p1/memory/a.md"] != before


def test_home_files_never_follow_a_link_out(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("host file")
    (ws.path / ".home").mkdir()
    os.symlink(outside, ws.path / ".home" / "dir")
    os.symlink(outside / "secret.md", ws.path / ".home" / "file.md")
    assert ws.home_files(["**"]) == {}
    assert ws.read_home("dir/secret.md") is None and ws.read_home("file.md") is None
    with pytest.raises(Invalid):
        ws.read_home("../ws.git/config")


def test_a_home_that_is_a_link_is_no_home(ws, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.md").write_text("host file")
    os.symlink(outside, ws.path / ".home")
    assert ws.home_files(["**"]) == {} and ws.read_home("x.md") is None
    with pytest.raises(Invalid):
        ws.write(".home/y.md", "planted")
    assert sorted(p.name for p in outside.iterdir()) == ["x.md"]


@pytest.mark.parametrize("glob, path, matches", [
    ("*.md", "a.md", True), ("*.md", "d/a.md", False), ("**/a.md", "a.md", True), ("**/a.md", "x/y/a.md", True),
    ("d/**", "d/x/y", True), ("d/**", "e/x", False), ("d/?.md", "d/a.md", True), ("d/?.md", "d/ab.md", False),
    ("a.b", "aXb", False), ("p/*/m/**", "p/x/m/f", True), ("p/*/m/**", "p/x/y/m/f", False)])
def test_globs_match_paths_as_documented(glob, path, matches):
    assert bool(matcher([glob])(path)) is matches


def test_a_workspace_owned_by_someone_else_still_works(ws):
    if os.geteuid() != 0:
        pytest.skip("only root can give a directory away")
    ws.write("a.txt", "x")
    subprocess.run(["chown", "-R", "1000:1000", str(ws.path)], check=True)
    assert ws.snapshot("theirs") and ws.files() == ["a.txt"]


def test_no_git_is_said_up_front(monkeypatch):
    import harness_interface.workspace as w
    monkeypatch.setattr(w.shutil, "which", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="git is required"):
        require_git()
