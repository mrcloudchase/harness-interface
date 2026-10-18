"""Layer 6: where each run goes. A Placement gives every run its runtime, built for the run's
sandbox and provider, and cleans up after a crash."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..execution import Runtime
from ..resources import Resolved
from ..runtimes import Docker, DockerRuntime, LocalRuntime, Sandbox


class Placement(Protocol):
    name: str

    def runtime(self, resolved: Resolved) -> Runtime: ...

    def image(self, sandbox: Sandbox) -> str | None: ...

    async def recover(self) -> None: ...


class DockerPlacement:
    """Every run in a fresh container of its harness's sandbox, reaching only its provider and the
    hosts its sandbox allows, with the harness's scripts mounted read-only."""
    name = "docker"

    def __init__(self, build_logs: Path):
        self.engine = Docker(build_logs)

    def runtime(self, resolved: Resolved) -> Runtime:
        return DockerRuntime(self.engine, resolved.sandbox, egress=[resolved.provider.host], mounts=[resolved.scripts])

    def image(self, sandbox: Sandbox) -> str:
        return sandbox.tag

    async def recover(self) -> None:
        await self.engine.recover()


class LocalPlacement:
    """Every run as a plain process on this machine: no isolation, and sandboxes are ignored."""
    name = "local"

    def runtime(self, resolved: Resolved) -> Runtime:
        return LocalRuntime()

    def image(self, sandbox: Sandbox) -> None:
        return None

    async def recover(self) -> None:
        return None
