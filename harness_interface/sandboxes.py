"""Layer 4: where a harness runs. A sandbox is an image the org named or a Dockerfile it gave, with
nothing of ours and nothing of any harness in it. The harness's CLI arrives as a tools layer:
`install.sh` run once in that image, into a directory cached per (harness version, image), mounted
read-only at the same path on every turn. Runs are the Docker runtime's, with the sandbox's limits
and egress.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import shutil
import time
from pathlib import Path
from typing import AsyncIterator, Sequence

from .execution import Event, Outcome, Spec
from .harness import Config
from .runtimes.docker import DockerRuntime, Images, Provider, sweep, whole
from .store import Sandbox

MARKER = ".hi-installed"
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class InstallFailed(RuntimeError):
    pass


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


def describe(outcome: Outcome) -> str:
    if outcome.kind == "failed":
        return f"could not start: {outcome.reason}"
    if outcome.kind == "timed_out":
        return "ran out of time"
    return f"exited {outcome.code}" if outcome.code is not None else "was killed"


def path_with(tools: Path) -> str:
    return f"{tools}/bin:{SYSTEM_PATH}"


class Runtimes:
    """Images, tools layers and runtimes for one server, whose runs carry one owner."""

    def __init__(self, logs: Path, ca_file: Path | None, owner: str):
        self.images, self.ca_file, self.owner = Images(logs), ca_file, owner

    async def recover(self) -> None:
        """Remove what this server's runs left behind when a crash cut them off."""
        await sweep(self.owner)

    async def image_for(self, sandbox: Sandbox) -> str:
        if sandbox.dockerfile:
            return await self.images.ensure(f"{sandbox.org}-{sandbox.name}", sandbox.dockerfile)
        return await Images.pull(sandbox.image)

    def runtime(self, image: str, sandbox: Sandbox, *, read_only: Sequence[Path] = (), writable: Sequence[Path] = (),
                provider: Provider | None = None, egress: Sequence[str] = ()) -> DockerRuntime:
        return DockerRuntime(image, read_only=read_only, writable=writable, egress=[*sandbox.egress, *egress],
                             provider=provider, ca_file=self.ca_file, owner=self.owner,
                             memory=sandbox.memory, pids=sandbox.pids)

    async def tools_for(self, folder: Path, config: Config, root: Path, sandbox: Sandbox, image: str) -> Path:
        """The harness's tools in this image, installed now unless they are already."""
        image_id, arch = await Images.identity(image)
        root.mkdir(parents=True, exist_ok=True)
        tools, log = root / f"{sandbox.name}-{image_id[:12]}", root / f"{sandbox.name}-{image_id[:12]}.log"
        async with locked(root / f".{tools.name}.lock"):
            if (tools / MARKER).is_file():
                return tools
            shutil.rmtree(tools, ignore_errors=True)
            tools.mkdir()
            began = time.monotonic()
            try:
                outcome = await self._install(folder, config, tools, sandbox, image, log)
            except BaseException:
                await asyncio.shield(asyncio.to_thread(shutil.rmtree, tools, True))
                raise
            if not outcome.ok:
                await asyncio.to_thread(shutil.rmtree, tools, True)
                tail = log.read_text(errors="replace")[-2000:] if log.is_file() else ""
                raise InstallFailed(f"install.sh {describe(outcome)} in sandbox {sandbox.name}; its log ends:\n{tail}")
            (tools / MARKER).write_text(json.dumps({"image": image_id, "arch": arch,
                                                    "seconds": round(time.monotonic() - began, 1)}))
            return tools

    async def _install(self, folder: Path, config: Config, tools: Path, sandbox: Sandbox, image: str, log: Path) -> Outcome:
        runtime = self.runtime(image, sandbox, read_only=(folder,), egress=config.install_egress)
        env = {"HI_TOOLS": str(tools), "HI_HARNESS_DIR": str(folder), "HOME": "/tmp", "PATH": path_with(tools)}
        execution = await runtime.start(Spec(("bash", str(folder / "install.sh")), env=env, workspace=tools,
                                             timeout_s=config.install_timeout_s))
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


def log_line(event: Event) -> bytes:
    if event.stream != "door":
        return event.data
    return b"".join(b"door: " + line + b"\n" for line in event.data.splitlines())
