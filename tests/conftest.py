"""Fixtures every test may use: a fake `docker` on PATH (tests/fakes/docker), with its state and calls."""
import json
import os
from pathlib import Path

import pytest

FAKES = Path(__file__).parent / "fakes"


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    state = tmp_path / "docker"
    state.mkdir()
    monkeypatch.setenv("PATH", f"{FAKES}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_CONFIG", str(state))                       # the fake keeps its state there
    monkeypatch.setenv("EXT_ANTHROPIC_API_KEY", "sk-from-the-host")        # as on this machine: never passed on
    monkeypatch.setattr("harness_interface.runtimes.docker.SECRETS", tmp_path / "shm")
    (tmp_path / "shm").mkdir()
    (FAKES / "docker").chmod(0o755)
    return FakeDocker(state)


class FakeDocker:
    """The fake's state directory, and every call it was given."""

    def __init__(self, state: Path):
        self.state = state

    def __truediv__(self, name: str) -> Path:
        return self.state / name

    def calls(self) -> list[list[str]]:
        p = self.state / "calls"
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def run(self) -> list[str]:
        return next(c for c in self.calls() if c[0] == "run" and "hi-run-" in c[c.index("--name") + 1])

    def door(self) -> list[str]:
        return next(c for c in self.calls() if c[0] == "run" and "hi-door-" in c[c.index("--name") + 1])

    def name(self, call: list[str]) -> str:
        return call[call.index("--name") + 1]

    def client_env(self, call: list[str]) -> dict:
        return json.loads((self.state / f"{self.name(call)}.client-env").read_text())

    def torn_down(self) -> bool:
        calls = self.calls()
        made = {self.name(c) for c in calls if c[0] == "run"}
        removed = {n for c in calls if c[:2] == ["rm", "-f"] for n in c[2:]}
        networks = {c[3] for c in calls if c[:3] == ["network", "create", "--internal"]}
        gone = {n for c in calls if c[:3] == ["network", "rm", "-f"] for n in c[3:]}
        return made <= removed and networks <= gone
