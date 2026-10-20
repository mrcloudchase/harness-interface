"""Layer 2: a working directory, and what changed in it.

A workspace's history is a git repository kept beside it, never inside: what runs in the workspace
can write anything there (a project's own `.git/` included) and none of it is a hook, a config or an
object of the history the server commits to. Each snapshot is a commit, so what changed between two
snapshots, and every file as a snapshot left it, can be read at any time, byte for byte; while
something is still working, its changes so far can be read without touching the history's index.

Internal paths are never part of a change, a listing or a read: `.home/` (the harness's config and
state), `.git/` (a project's own repository) and `__pycache__/`. The one way into `.home/` is by glob,
for the artifacts a harness reports. No path ever leads outside: a link that does is refused.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Iterable

from .errors import Invalid
from .runtimes.process import host_env

HOME = ".home"
INTERNAL = (f"{HOME}/", ".git/", "__pycache__/")
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
AUTHOR = ("-c", "user.name=harness-interface", "-c", "user.email=harness-interface@localhost")


def require_git() -> None:
    """Every workspace has a git history: say so up front, not on the first request."""
    if not shutil.which("git", path=host_env().get("PATH")):
        raise RuntimeError("git is required: every workspace keeps its history in git. Install git, then start again.")


def internal(rel: str) -> bool:
    """Whether a workspace-relative path is internal, and so never listed, changed or read."""
    return f"{rel}/".startswith(INTERNAL) or "/__pycache__/" in f"/{rel}/"


def matcher(globs: Iterable[str]) -> Callable[[str], bool]:
    """Whether a relative path matches any of `globs`: `*` and `?` within one name, `**` across any
    number of directories (at the end: everything beneath)."""
    def regex(glob: str) -> str:
        parts = glob.split("/")
        out = ""
        for i, part in enumerate(parts):
            last = i == len(parts) - 1
            if part == "**":
                out += ".*" if last else "(?:[^/]+/)*"
            else:
                out += "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in part)
                out += "" if last else "/"
        return out
    compiled = [re.compile(regex(g)) for g in globs]
    return lambda rel: any(c.fullmatch(rel) for c in compiled)


class Workspace:
    def __init__(self, path: Path, history: Path | None = None):
        self.path = Path(path).absolute()
        self.history = Path(history).absolute() if history else self.path.with_name(f"{self.path.name}.git")

    def _git(self, *args: str, index: str | None = None) -> subprocess.CompletedProcess:
        # Only the history's own settings count: no system or user config, no hooks, nothing the
        # workspace holds. The workspace may belong to the sandbox's user, which git must be told is safe.
        env = {**host_env(), "GIT_DIR": str(self.history), "GIT_WORK_TREE": str(self.path),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, **({"GIT_INDEX_FILE": index} if index else {})}
        return subprocess.run(["git", "-c", "safe.directory=*", "-c", f"core.hooksPath={os.devnull}",
                               "-c", "core.quotePath=false", *args], cwd=self.path, env=env, capture_output=True)

    def _out(self, *args: str, index: str | None = None) -> str:
        done = self._git(*args, index=index)
        if done.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {done.stderr.decode(errors='replace')[-500:]}")
        return done.stdout.decode()

    def init(self) -> None:
        """Create it and its history, or make sure of them."""
        self.path.mkdir(parents=True, exist_ok=True)
        if not (self.history / "HEAD").exists():
            self._out("init", "-q")
        (self.history / "info").mkdir(exist_ok=True)
        (self.history / "info" / "exclude").write_text(f"/{HOME}/\n__pycache__/\n")   # git never adds a .git

    def resolve(self, rel: str) -> Path:
        """The absolute path of `rel`, which must lead inside the workspace, links followed."""
        p = (self.path / rel).resolve()
        if not p.is_relative_to(self.path.resolve()) or p == self.path.resolve():
            raise Invalid(f"path escapes the workspace: {rel!r}")
        return p

    def write(self, rel: str, content: str | bytes) -> None:
        p = self.resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode() if isinstance(content, str) else content)

    def delete(self, rel: str) -> None:
        """Remove a file, or a link (never what it points at); nothing if it isn't there."""
        path = Path(rel)
        if path.name in ("", ".", "..") or rel.endswith("/"):
            raise Invalid(f"not a file: {rel!r}")
        parent = self.path.resolve() if str(path.parent) == "." else self.resolve(str(path.parent))
        p = parent / path.name
        if p.is_symlink() or p.is_file():
            p.unlink()

    def snapshot(self, message: str) -> str:
        """Commit everything as it is now, and return the commit."""
        self._out("add", "-A")
        self._out(*AUTHOR, "commit", "-q", "--allow-empty", "--no-verify", "-m", message)
        return self._out("rev-parse", "HEAD").strip()

    def _head(self) -> str:
        done = self._git("rev-parse", "-q", "--verify", "HEAD")
        return done.stdout.decode().strip() if done.returncode == 0 else EMPTY_TREE

    def _tree(self, head: str | None) -> str:
        """`head`, or the files as they are right now, staged in a throwaway index."""
        if head:
            return head
        with tempfile.TemporaryDirectory() as tmp:
            index = str(Path(tmp) / "index")
            self._out("add", "-A", index=index)
            return self._out("write-tree", index=index).strip()

    def changes(self, base: str | None = None, head: str | None = None) -> tuple[list[str], list[str]]:
        """From `base` (by default the last snapshot) to `head` (by default now): the paths added or
        modified, and the paths deleted."""
        out = self._out("diff", "--name-status", "--no-renames", "-z", base or self._head(), self._tree(head))
        fields = out.split("\0")
        changed, deleted = [], []
        for status, rel in zip(fields[0::2], fields[1::2]):
            if rel and not internal(rel):
                (deleted if status == "D" else changed).append(rel)
        return sorted(changed), sorted(deleted)

    def diff(self, base: str, head: str | None = None) -> str:
        """What changed from `base` to `head`; with no `head`, to the files as they are right now."""
        return self._out("diff", "--no-color", "--no-ext-diff", base, self._tree(head))

    def files(self, commit: str | None = None) -> list[str]:
        """Every file, as `commit` left them, or as they are now."""
        found = self._out("ls-tree", "-r", "-z", "--name-only", self._tree(commit)).split("\0")
        return sorted(p for p in found if p and not internal(p))

    def read(self, rel: str, commit: str | None = None) -> bytes | None:
        """A file as `commit` left it, or as it is now; None if it isn't there or is internal."""
        inside = self.resolve(rel).relative_to(self.path.resolve()).as_posix()
        if internal(inside):
            return None
        if not commit:
            p = self.path / inside
            return p.read_bytes() if p.is_file() else None
        shown = self._git("cat-file", "blob", f"{commit}:{inside}")
        return shown.stdout if shown.returncode == 0 else None

    # .home/, by glob only
    def home_files(self, globs: Iterable[str]) -> dict[str, str]:
        """Every regular file under `.home/` matching `globs`, by its path there, with a digest of its
        content. A link is never followed, nor a `.home` that is one."""
        home, matches = self.path / HOME, matcher(globs)
        if home.is_symlink() or not home.is_dir():
            return {}
        found = {}
        for root, _, names in os.walk(home):        # links to directories are listed, never entered
            for name in names:
                p = Path(root, name)
                rel = p.relative_to(home).as_posix()
                if not p.is_symlink() and p.is_file() and matches(rel):
                    found[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        return found

    def read_home(self, rel: str) -> bytes | None:
        """A file under `.home/` by its path there; None if it isn't a regular file reached without a link."""
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise Invalid(f"path escapes the home: {rel!r}")
        p = self.path
        for part in (HOME, *path.parts):
            p = p / part
            if p.is_symlink():
                return None
        return p.read_bytes() if p.is_file() else None
