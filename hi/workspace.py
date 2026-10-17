"""A conversation's directory: files go in, the harness works, git tells us what changed."""
from __future__ import annotations

import subprocess
from pathlib import Path

INTERNAL = (".hi/", ".home/", ".git/", "__pycache__/")   # server and CLI state, and build noise: never "produced"


class Workspace:
    def __init__(self, path: Path):
        self.path = path

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=self.path, capture_output=True, text=True)

    def init(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / ".hi").mkdir(exist_ok=True)
        if not (self.path / ".git").exists():
            self._git("init", "-q")
            (self.path / ".gitignore").write_text("".join(f"{d}\n" for d in INTERNAL))

    def write(self, rel: str, content: str) -> None:
        p = self.resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def resolve(self, rel: str) -> Path:
        p = (self.path / rel).resolve()
        if not p.is_relative_to(self.path.resolve()):
            raise ValueError(f"path escapes the workspace: {rel}")
        return p

    def changed(self) -> list[str]:
        """Paths added or modified since the last commit, the harness's own state excluded."""
        paths = []
        for line in self._git("status", "--porcelain", "-uall").stdout.splitlines():
            rel = line[3:].strip().strip('"')
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1]
            if rel and not rel.startswith(INTERNAL) and "/__pycache__/" not in rel and rel != ".gitignore" and not line.startswith(" D"):
                paths.append(rel)
        return sorted(paths)

    def commit(self, message: str) -> None:
        self._git("add", "-A")
        self._git("-c", "user.name=hi", "-c", "user.email=hi@localhost",
                  "commit", "-q", "--allow-empty", "-m", message)
