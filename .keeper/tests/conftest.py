"""A throwaway project for every test: a git repository with an origin, Keeper's real loops and
prompts, and a keeper.toml whose checks are small shell commands the test controls."""
import shutil
import sys
from pathlib import Path

import pytest

KEEPER = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(KEEPER / "engine"), str(Path(__file__).parent)]

from config import Config  # noqa: E402
from context import Context  # noqa: E402
from fakes import FakeGitHub, git  # noqa: E402
from governor import Governor  # noqa: E402
from workspace import Workspace  # noqa: E402

TOML = """
spec = "0.3"
[human]
login = "owner"
[branches]
work = "main"
release = "main"
[checks]
test = "sh check.sh"
[live]
command = "sh live.sh"
[tiers]
human = ["VISION.md", "keeper.toml", ".github/*", "core/*"]
[reviewers]
"*" = ["correctness"]
[roles]
planner = "plan-cli"
maker = "make-cli"
checker = "check-cli"
writer = "write-cli"
[providers]
[budget]
run_usd = 5
day_usd = 40
week_usd = 200
open_prs = 3
tries = 2
[rigor]
size_budget = { path = "src", glob = "*.py", lines = 50 }
[upgrade]
targets = ["deps.txt"]
versions = "echo 'left-pad pinned 1.0 latest 1.3'"
[publish]
"CHANGELOG.md" = "release.yml"
[schedule]
"0 3 * * *" = ["nightly", "status"]
"""

VISION = """# Vision
## North star
A test project.
## Themes
1. **Fast tests**: they run in a second.
2. **Clear errors**: every failure says why.
## Non-goals
- Anything else.
"""


@pytest.fixture
def project(tmp_path):
    """A project with an origin; returns its checkout's root."""
    origin, root = tmp_path / "origin.git", tmp_path / "project"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    root.mkdir()
    shutil.copytree(KEEPER / "loops", root / ".keeper" / "loops")
    shutil.copytree(KEEPER / "prompts", root / ".keeper" / "prompts")
    (root / "keeper.toml").write_text(TOML)
    (root / "VISION.md").write_text(VISION)
    (root / "AGENTS.md").write_text("# Agents\nKeep it simple.\n")
    (root / "check.sh").write_text("test ! -f broken.txt\n")
    (root / "live.sh").write_text("test ! -f live-broken.txt\n")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github" / "workflows" / "release.yml").write_text("on: workflow_dispatch\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_add():\n    assert 1 + 1 == 2\n    assert True\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "-q", "origin", "main")
    return root


@pytest.fixture
def gh():
    return FakeGitHub(human="owner")


def make_ctx(root: Path, gh, runtime=None, enabled: bool = True) -> Context:
    config = Config.load(root)
    return Context(config, gh, Workspace(root), Governor(config, gh, enabled), runtime)
