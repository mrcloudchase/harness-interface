"""Layer 4: one worker node's capabilities: the platform's base image, a package's tools layer in that
image (`install.sh` run once per package version, cached on the node), and a runtime for a turn with
a tenant's uid and ceilings. Nothing of any package is in the image; the CLI arrives as the tools
layer, mounted read-only at the same path on every turn.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Sequence

from .execution import Event, Outcome, Spec
from .harness import Config
from .limits import Limits
from .runtimes.docker import DockerRuntime, Resources, build_base, identity, pull, sweep, whole

MARKER = ".hi-installed"
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
UID_BASE, UID_RANGE = 100_000, 100_000


class InstallFailed(RuntimeError):
    pass


def uid_for(tenant: str) -> int:
    """The unprivileged uid a tenant's runs use on a node: the same for the same tenant everywhere."""
    return UID_BASE + int(hashlib.sha256(tenant.encode()).hexdigest()[:8], 16) % UID_RANGE


def path_with(tools: Path) -> str:
    return f"{tools}/bin:{SYSTEM_PATH}"


def describe(outcome: Outcome) -> str:
    if outcome.kind == "failed":
        return f"could not start: {outcome.reason}"
    if outcome.kind == "timed_out":
        return "ran out of time"
    return f"exited {outcome.code}" if outcome.code is not None else "was killed"


@contextlib.asynccontextmanager
async def locked(path: Path) -> AsyncIterator[None]:
    """Hold an exclusive lock on `path`, waiting for it without blocking the loop."""
    with open(path, "a") as f:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                await asyncio.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def log_line(event: Event) -> bytes:
    if event.stream != "door":
        return event.data
    return b"".join(b"door: " + line + b"\n" for line in event.data.splitlines())


@dataclass
class Node:
    """How this node runs things: the base image (the shipped one, built here, when empty), the
    sandboxed runtime if any, the CA file, whether private egress is allowed (a self-hosted box with
    internal hosts), and the owner its runs carry."""
    image: str
    owner: str
    runtime: str = ""
    ca_file: Path | None = None
    allow_private: bool = False

    async def prepare(self) -> str:
        """The base image, built or pulled once; its id, which keys the tools layers."""
        self.image = await build_base() if not self.image else await pull(self.image)
        return (await identity(self.image))[0]

    async def recover(self) -> None:
        await sweep(self.owner)

    def runtime_for(self, tenant: str, limits: Limits, *, read_only: Sequence[Path] = (), writable: Sequence[Path] = (),
                    egress: Sequence[str] = (), gateway_url: str = "", token: str = "") -> DockerRuntime:
        return DockerRuntime(self.image, uid=uid_for(tenant), limits=Resources(limits.cpus, limits.memory, limits.pids),
                             read_only=read_only, writable=writable, egress=egress, gateway_url=gateway_url, token=token,
                             ca_file=self.ca_file, owner=self.owner, runtime=self.runtime, allow_private=self.allow_private)

    async def tools_for(self, tenant: str, limits: Limits, folder: Path, config: Config, root: Path, image_id: str) -> Path:
        """The package's tools in the base image, installed now unless they are already."""
        root.mkdir(parents=True, exist_ok=True)
        tools, log = root / f"{folder.name}-{image_id[:12]}", root / f"{folder.name}-{image_id[:12]}.log"
        async with locked(root / f".{tools.name}.lock"):
            if (tools / MARKER).is_file():
                return tools
            shutil.rmtree(tools, ignore_errors=True)
            tools.mkdir()
            began = time.monotonic()
            try:
                outcome = await self._install(tenant, limits, folder, config, tools, log)
            except BaseException:
                await asyncio.shield(asyncio.to_thread(shutil.rmtree, tools, True))
                raise
            if not outcome.ok:
                await asyncio.to_thread(shutil.rmtree, tools, True)
                tail = log.read_text(errors="replace")[-2000:] if log.is_file() else ""
                raise InstallFailed(f"install.sh {describe(outcome)}; its log ends:\n{tail}")
            (tools / MARKER).write_text(json.dumps({"image": image_id, "seconds": round(time.monotonic() - began, 1)}))
            return tools

    async def _install(self, tenant: str, limits: Limits, folder: Path, config: Config, tools: Path, log: Path) -> Outcome:
        runtime = self.runtime_for(tenant, limits, read_only=(folder,), writable=(tools,), egress=config.install_egress)
        env = {"HI_TOOLS": str(tools), "HI_HARNESS_DIR": str(folder), "HOME": "/tmp", "PATH": path_with(tools)}
        execution = await runtime.start(Spec(("bash", str(folder / "install.sh")), env=env, workspace=tools,
                                             timeout_s=min(config.install_timeout_s, limits.install_timeout_s)))
        try:
            with open(log, "wb") as f:
                async for event in execution.events():
                    f.write(log_line(event))
                    f.flush()
            return await execution.wait()
        except BaseException:
            execution.kill()
            await whole(execution.wait())
            raise
