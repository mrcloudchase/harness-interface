"""Layer 2: a working directory, and what changed in it.

A workspace is a git repository. Each snapshot is a commit, so what changed between two snapshots,
and every file as a snapshot left it, can be read at any time; while something is still working,
its changes so far can be read without touching the index it might be using. Internal paths are
never part of a change, a listing or a read.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import Invalid

# The server's own state, a CLI's private state (its sessions and credentials), git, and build noise.
INTERNAL = (".hi/", ".home/", ".git/", "__pycache__/")


def require_git() -> None:
    """Every workspace is a git repository: say so up front, not on the first request."""
    if not shutil.which("git"):
        raise RuntimeError("git is required: every workspace is a git repository. Install git, then start again.")


def internal(rel: str) -> bool:
    """Whether a workspace-relative path is internal, and so never listed, changed or read."""
    return f"{rel}/".startswith(INTERNAL) or "/__pycache__/" in f"/{rel}/"


class Workspace:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _git(self, *args: str, text: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        # Something running in a sandbox may own the directory, and git refuses a repository owned
        # by someone else unless told it is safe.
        return subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=self.path, capture_output=True,
                              text=text, env={**os.environ, **env} if env else None)

    def init(self) -> None:
        """Create it, or make sure of it. The internal paths are ignored in .git/info/exclude, not
        .gitignore: a .gitignore is the project's own file, and anything may replace it."""
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / ".hi").mkdir(exist_ok=True)
        if not (self.path / ".git").exists():
            self._git("init", "-q")
        (self.path / ".git" / "info").mkdir(exist_ok=True)
        (self.path / ".git" / "info" / "exclude").write_text(
            "".join(f"/{d}\n" for d in INTERNAL if d != ".git/") + "__pycache__/\n")

    def resolve(self, rel: str) -> Path:
        """The absolute path of `rel`, which must stay inside the workspace, links followed."""
        p = (self.path / rel).resolve()
        if not p.is_relative_to(self.path.resolve()):
            raise Invalid(f"path escapes the workspace: {rel}")
        return p

    def write(self, rel: str, content: str) -> None:
        p = self.resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def snapshot(self, message: str) -> str:
        """Commit everything as it is now, and return the commit."""
        self._git("add", "-A")
        self._git("-c", "user.name=harness-interface", "-c", "user.email=harness-interface@localhost",
                  "commit", "-q", "--allow-empty", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def changes(self) -> tuple[list[str], list[str]]:
        """Since the last snapshot: the paths added or modified, and the paths deleted."""
        changed, deleted = [], []
        for line in self._git("status", "--porcelain", "-uall").stdout.splitlines():
            rel = line[3:].strip().strip('"')
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1]
            if rel and not internal(rel):
                (deleted if "D" in line[:2] else changed).append(rel)
        return sorted(changed), sorted(deleted)

    def diff(self, base: str, head: str | None = None) -> str:
        """What changed from `base` to `head`; with no `head`, to the files as they are right now.
        That case stages into a throwaway index, so the workspace's own index is never touched."""
        if head:
            return self._git("diff", "--no-color", base, head).stdout
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            self._git("read-tree", base, env=env)
            self._git("add", "-A", env=env)
            return self._git("diff", "--no-color", "--cached", base, env=env).stdout

    def files(self, commit: str | None = None) -> list[str]:
        """Every file, as `commit` left them, or as they are now."""
        if commit:
            found = self._git("ls-tree", "-r", "--name-only", commit).stdout.splitlines()
        else:
            found = [str(p.relative_to(self.path)) for p in self.path.rglob("*") if p.is_file()]
        return sorted(p for p in found if not internal(p))

    def read(self, rel: str, commit: str | None = None) -> bytes | None:
        """A file as `commit` left it, or as it is now; None if it isn't there or is internal."""
        inside = self.resolve(rel).relative_to(self.path.resolve()).as_posix()
        if internal(inside):
            return None
        if not commit:
            p = self.path / inside
            return p.read_bytes() if p.is_file() else None
        shown = self._git("show", f"{commit}:{inside}", text=False)
        return shown.stdout if shown.returncode == 0 else None
