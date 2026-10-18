"""A conversation's directory: files go in, the harness works, git tells us what changed. Each
turn ends in a commit, so every response's files and changes can be read as that turn left them."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import ClientError

INTERNAL = (".hi/", ".home/", ".git/", "__pycache__/")   # server and CLI state, and build noise: never "produced"


def require_git() -> None:
    """Every workspace is a git repository: say so at startup, not on the first request."""
    if not shutil.which("git"):
        raise RuntimeError("git is required: every workspace is a git repository. Install git, then start the server again.")


class Workspace:
    def __init__(self, path: Path):
        self.path = path

    def _git(self, *args: str, text: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        # The sandbox user may own the directory; git refuses a repository owned by someone else
        # unless told it is safe.
        return subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=self.path, capture_output=True,
                              text=text, env={**os.environ, **env} if env else None)

    def init(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / ".hi").mkdir(exist_ok=True)
        if not (self.path / ".git").exists():
            self._git("init", "-q")
        # The internal paths are ignored in .git/info/exclude, not .gitignore: a .gitignore is the
        # project's own file, and a request or a harness may replace it. The harness's own state
        # (.home, with its credentials) must never be committed, diffed or listed.
        (self.path / ".git" / "info").mkdir(exist_ok=True)
        (self.path / ".git" / "info" / "exclude").write_text("".join(f"/{d}\n" for d in INTERNAL if d != ".git/") + "__pycache__/\n")

    def write(self, rel: str, content: str) -> None:
        p = self.resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def resolve(self, rel: str) -> Path:
        p = (self.path / rel).resolve()
        if not p.is_relative_to(self.path.resolve()):
            raise ClientError(f"path escapes the workspace: {rel}")
        return p

    def changes(self) -> tuple[list[str], list[str]]:
        """Since the last commit: the paths added or modified, and the paths deleted. The
        harness's own state is excluded."""
        changed, deleted = [], []
        for line in self._git("status", "--porcelain", "-uall").stdout.splitlines():
            rel = line[3:].strip().strip('"')
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1]
            if rel and not rel.startswith(INTERNAL) and "/__pycache__/" not in rel:
                (deleted if "D" in line[:2] else changed).append(rel)
        return sorted(changed), sorted(deleted)

    def commit(self, message: str) -> str:
        """Commit everything as it is now, and return the commit."""
        self._git("add", "-A")
        self._git("-c", "user.name=harness-interface", "-c", "user.email=harness-interface@localhost",
                  "commit", "-q", "--allow-empty", "-m", message)
        return self._git("rev-parse", "HEAD").stdout.strip()

    def diff(self, base: str, head: str | None = None) -> str:
        """What changed from `base` to `head`; with no `head`, to the files as they are right
        now, while a run is still going. That case stages into a throwaway index, so the
        workspace's own index, which the harness may be using, is never touched."""
        if head:
            return self._git("diff", "--no-color", base, head).stdout
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            self._git("read-tree", base, env=env)
            self._git("add", "-A", env=env)
            return self._git("diff", "--no-color", "--cached", base, env=env).stdout

    def files(self, commit: str | None = None) -> list[str]:
        """Every file in the workspace, as `commit` left it, or as it is now."""
        if commit:
            out = self._git("ls-tree", "-r", "--name-only", commit).stdout.splitlines()
        else:
            out = [str(p.relative_to(self.path)) for p in self.path.rglob("*") if p.is_file()]
        return sorted(p for p in out if not p.startswith(INTERNAL) and "/__pycache__/" not in p)

    def read(self, rel: str, commit: str | None = None) -> bytes | None:
        """A file as `commit` left it, or as it is now; None if it isn't there."""
        p = self.resolve(rel)
        inside = p.relative_to(self.path.resolve()).as_posix()
        if f"{inside}/".startswith(INTERNAL) or "/__pycache__/" in f"/{inside}/":
            return None                                # the server's and the harness's own state: never served
        if not commit:
            return p.read_bytes() if p.is_file() else None
        shown = self._git("show", f"{commit}:{inside}", text=False)
        return shown.stdout if shown.returncode == 0 else None
