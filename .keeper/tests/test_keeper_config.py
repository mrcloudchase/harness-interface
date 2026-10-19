"""keeper.toml and the loop documents: what loads, and what is refused before anything runs."""
import re
from pathlib import Path

import pytest

from config import Config, ConfigError, LoopDoc

REPO = Path(__file__).resolve().parents[2]


def test_the_projects_own_configuration_loads():
    c = Config.load(REPO)
    assert set(c.loops) == {"spec", "build", "repair", "flake", "upgrade", "strengthen", "simplify", "docs", "compat", "evolve"}
    assert c.human and c.checks and c.work and c.release


def test_the_workflow_runs_exactly_the_scheduled_crons():
    workflow = (REPO / ".github" / "workflows" / "keeper.yml").read_text()
    assert set(re.findall(r'cron: "([^"]+)"', workflow)) == set(Config.load(REPO).schedule)


def test_a_loop_needs_a_deterministic_verifier():
    with pytest.raises(ConfigError, match="command or rule"):
        LoopDoc(name="x", goal="do it", verifiers=[{"kind": "judge"}])
    with pytest.raises(ConfigError):
        LoopDoc(name="x", goal="do it", verifiers=[{"kind": "telepathy"}])
    assert LoopDoc(name="x", goal="do it", verifiers=[{"kind": "rule", "rules": ["no_workflows"]}])


def test_refusals(project):
    toml = (project / "keeper.toml").read_text()
    (project / "keeper.toml").write_text(toml.replace("run_usd = 5", "run_usd = 0"))
    with pytest.raises(ConfigError, match="budget"):
        Config.load(project)
    (project / "keeper.toml").write_text(toml.replace('"*" = ["correctness"]', '"*" = ["astrology"]'))
    with pytest.raises(ConfigError, match="checker-astrology"):
        Config.load(project)
    (project / "keeper.toml").write_text(toml.replace('writer = "write-cli"\n', ""))
    with pytest.raises(ConfigError, match="writer"):
        Config.load(project)
    (project / "keeper.toml").write_text(toml)
    (project / ".keeper" / "loops" / "bad.toml").write_text('name = "other"\ngoal = "x"\nverifiers = [{ kind = "rule" }]\n')
    with pytest.raises(ConfigError, match="names its loop"):
        Config.load(project)


def test_roles_paths_and_switches(project):
    c = Config.load(project)
    assert c.harness("checker-security") == "check-cli" and c.harness("maker") == "make-cli"
    assert c.is_human_tier(".github/workflows/ci.yml") and c.is_human_tier("core/a/b.py") and not c.is_human_tier("src/app.py")
    assert c.reviewers_for(["src/app.py", "docs/a.md"]) == ["correctness"]
    assert not c.enabled(c.loops["strengthen"]) and c.enabled(c.loops["build"])
    assert c.tasks_for("0 3 * * *") == ["nightly", "status"] and c.tasks_for("never") == []
