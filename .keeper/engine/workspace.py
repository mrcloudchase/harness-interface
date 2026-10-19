"""The project's checkout on the runner, where the workflow acts on what agents propose: branches,
their files, commits and pushes, and the commands that check them. Nothing else in the engine runs
git."""
from __future__ import annotations

import base64
import subprocess
from pathlib import Path

from env import clean

BOT = ("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
# What running a project leaves behind, and an agent's own state: never part of a change. Kept in
# .git/info/exclude, so a project's own .gitignore can't let it in.
NOISE = ("__pycache__/", "*.pyc", ".pytest_cache/", ".ruff_cache/", ".mypy_cache/", ".venv/", "node_modules/",
         ".home/", ".hi/", "keeper.json")
FILE_CAP, TOTAL_CAP = 200_000, 4_000_000    # what an agent is handed, at most


class GitError(RuntimeError):
    pass


class Workspace:
    def __init__(self, root: Path, token: str = "", secrets: dict[str, str] | None = None):
        """`token` reaches only git's own requests to GitHub; `secrets` only commands run `with_secrets`."""
        self.root, self._token, self._secrets = Path(root), token, dict(secrets or {})
        exclude = self.root / ".git" / "info" / "exclude"
        if exclude.parent.is_dir() and "keeper.json" not in (exclude.read_text() if exclude.is_file() else ""):
            with exclude.open("a") as f:
                f.write("\n# Keeper: never part of a change\n" + "\n".join(NOISE) + "\n")

    def __repr__(self) -> str:
        return f"Workspace({self.root})"

    def git(self, *args: str, check: bool = True, remote: bool = False, env: dict | None = None) -> str:
        auth = []
        if remote and self._token:                           # never on commands that run project code
            basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
            auth = ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]
        r = subprocess.run(["git", "-c", f"user.name={BOT[0]}", "-c", f"user.email={BOT[1]}", *auth, *args],
                           cwd=self.root, capture_output=True, text=True, env=env or clean())
        if check and r.returncode != 0:
            raise GitError(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[-500:]}")
        return r.stdout.strip()

    def run(self, command: str, timeout: int = 3600, with_secrets: bool = False) -> tuple[bool, str]:
        """A shell command in the checkout, with no credentials: whether it passed, and the end of
        what it printed. `with_secrets` gives it the provider keys a live run needs, and no more."""
        env = clean(self._secrets if with_secrets else None)
        try:
            r = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, text=True,
                               timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return False, f"{command}: timed out after {timeout}s"
        return r.returncode == 0, (r.stdout + r.stderr)[-4000:]

    # ── branches ───────────────────────────────────────────────────────────────────────────────
    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def start(self, branch: str, base: str) -> str:
        """Check out `branch` as it is on origin, or new from `base`. Returns the commit it starts at."""
        self.git("fetch", "-q", "origin", base, remote=True)
        if self.git("ls-remote", "--heads", "origin", branch, remote=True):
            self.git("fetch", "-q", "origin", branch, remote=True)
            self.git("checkout", "-q", "-B", branch, f"origin/{branch}")
        else:
            self.git("checkout", "-q", "-B", branch, f"origin/{base}")
        return self.head()

    def fetch(self, ref: str) -> None:
        self.git("fetch", "-q", "origin", ref, remote=True)

    def checkout(self, ref: str) -> None:
        self.fetch(ref)
        self.git("checkout", "-q", "--detach", "FETCH_HEAD")

    def reset(self, to: str = "HEAD") -> None:
        self.git("reset", "-q", "--hard", to)
        self.git("clean", "-qfd")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.head()

    def push(self, branch: str) -> None:
        self.git("push", "-q", "--force-with-lease", "origin", f"HEAD:refs/heads/{branch}", remote=True)

    # ── files ──────────────────────────────────────────────────────────────────────────────────
    def seed(self) -> dict[str, str]:
        """The project's text files, as an agent's workspace starts: binaries and large files left out."""
        out, total = {}, 0
        for rel in self.git("ls-files").splitlines():
            p = self.root / rel
            if not p.is_file() or p.stat().st_size > FILE_CAP or total + p.stat().st_size > TOTAL_CAP:
                continue
            try:
                out[rel] = p.read_text()
            except UnicodeDecodeError:
                continue
            total += p.stat().st_size
        return out

    def apply(self, changes: dict[str, bytes | None]) -> None:
        for rel, data in changes.items():
            p = (self.root / rel).resolve()
            if not p.is_relative_to(self.root.resolve()) or rel.startswith(".git/"):
                raise GitError(f"refusing a path outside the project: {rel}")
            if data is None:
                p.unlink(missing_ok=True)
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)

    def changed(self, base: str) -> list[str]:
        """Every path that differs from `base`, committed or not."""
        self.git("add", "-A")
        return sorted(self.git("diff", "--cached", "--name-only", base).splitlines())

    def diff(self, base: str) -> str:
        self.git("add", "-A")
        return self.git("diff", "--cached", base)

    def file_at(self, ref: str, path: str) -> str | None:
        r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=self.root, capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None

    def files_at(self, ref: str) -> list[str]:
        return self.git("ls-tree", "-r", "--name-only", ref).splitlines()

    def merge_base(self, a: str, b: str) -> str:
        return self.git("merge-base", a, b)

    # ── history ────────────────────────────────────────────────────────────────────────────────
    def commits(self, good: str, bad: str) -> list[str]:
        """The first-parent commits after `good`, up to `bad`, oldest first."""
        return self.git("rev-list", "--first-parent", "--reverse", f"{good}..{bad}").splitlines()

    def bisect(self, good: str, bad: str, command: str) -> str:
        """The first commit between `good` and `bad` on which `command` fails."""
        try:
            self.git("bisect", "start", "--first-parent", bad, good)
            out = self.git("bisect", "run", "sh", "-c", command, check=False,
                           env=clean(self._secrets))           # the live command needs its keys
            return next(line.split()[0] for line in out.splitlines() if "is the first bad commit" in line)
        finally:
            self.git("bisect", "reset", check=False)

    def revert(self, sha: str) -> None:
        parents = self.git("rev-list", "--parents", "-n", "1", sha).split()[1:]
        self.git("revert", "--no-edit", *(["-m", "1"] if len(parents) > 1 else []), sha)
