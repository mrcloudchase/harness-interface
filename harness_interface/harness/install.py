"""Layer 3: a harness's install, done once per version and cached.

`install.sh` fills a tools directory, `<root>/<name>-<key>`, where the key is a hash of `install.sh`,
`image.Dockerfile`, the base image's id and the CPU architecture: a change to any of them is a new
directory, a change to anything else in the folder is not. The directory is complete only once its
marker is written, last; an install that fails, times out or is cancelled leaves no directory; one
lock per key, so the same install never runs twice at once, across processes too. Its output, and the
door's log under Docker, go to `<root>/<name>-<key>.log`.

Under Docker, `install.sh` runs in the harness's image (the base image, `base.Dockerfile`, or the
folder's `image.Dockerfile` built FROM it) in the hardened container every run gets, as uid 1000,
with `HOME=/tmp`, the folder read-only, the tools directory read-write at its final path (npm and uv
write absolute paths), a door that reaches only `install.egress`, and no provider or secret at all.
On this machine it runs as a plain process, its HOME a scratch directory, with the same key scheme.
"""
from __future__ import annotations

import asyncio
import contextlib
import fcntl
import hashlib
import json
import platform
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from ..execution import Event, Outcome, Spec
from ..runtimes.docker import docker, whole
from .folder import BASE_FROM, HarnessFolder
from .placement import Placement

BASE_DOCKERFILE = Path(__file__).with_name("base.Dockerfile")
MARKER = ".hi-installed"


@dataclass(frozen=True)
class Installed:
    """A harness's tools directory, complete, and the image its responses run in (Docker only)."""
    path: Path
    image: str | None
    cached: bool                                     # it was there already
    log: Path


class InstallFailed(RuntimeError):
    def __init__(self, message: str, log: Path | None = None):
        super().__init__(message)
        self.log = log


def from_base(dockerfile: str, base: str) -> str:
    """An image.Dockerfile with its first instruction naming the base image by its tag."""
    lines = dockerfile.splitlines(keepends=True)
    first = next(i for i, line in enumerate(lines) if line.strip() == BASE_FROM)
    return "".join([*lines[:first], f"FROM {base}\n", *lines[first + 1:]])


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


class Installer:
    def __init__(self, root: Path, placement: Placement):
        self.root, self.placement = Path(root).absolute(), placement

    async def ensure(self, folder: HarnessFolder) -> Installed:
        """The folder's tools, installed now unless they are already. InstallFailed says why not."""
        image, base_id, arch = await self._image(folder)
        key = hashlib.sha256(b"\0".join([folder.install_sh, (folder.dockerfile or "").encode(), base_id.encode(),
                                         arch.encode()])).hexdigest()[:12]
        tools, log = self.root / f"{folder.name}-{key}", self.root / f"{folder.name}-{key}.log"
        self.root.mkdir(parents=True, exist_ok=True)
        async with locked(self.root / f".{folder.name}-{key}.lock"):
            if (tools / MARKER).is_file():
                return Installed(tools, image, True, log)
            shutil.rmtree(tools, ignore_errors=True)
            tools.mkdir()
            began = time.monotonic()
            try:
                outcome = await self._run(folder, tools, image, log)
            except BaseException:
                await asyncio.shield(asyncio.to_thread(shutil.rmtree, tools, True))
                raise
            if not outcome.ok:
                await asyncio.to_thread(shutil.rmtree, tools, True)
                tail = log.read_text(errors="replace")[-2000:]
                raise InstallFailed(f"the install of {folder.name} {describe(outcome)}; its log, {log}, ends:\n{tail}",
                                    log)
            (tools / MARKER).write_text(json.dumps({"harness": folder.name, "key": key, "base": base_id, "arch": arch,
                                                    "seconds": round(time.monotonic() - began, 1)}))
            return Installed(tools, image, False, log)

    async def _image(self, folder: HarnessFolder) -> tuple[str | None, str, str]:
        """The image installs and responses run in, the base image's id, and the CPU architecture."""
        images = self.placement.images
        if images is None:
            return None, "local", platform.machine()
        try:
            base = await images.ensure("base", BASE_DOCKERFILE.read_text())
            code, out = await docker("image", "inspect", "-f", "{{.Id}} {{.Architecture}}", base)
            if code != 0 or len(out.split()) != 2:
                raise RuntimeError(f"cannot inspect {base}: {out.strip()}")
            base_id, arch = out.split()
            if not folder.dockerfile:
                return base, base_id, arch
            return await images.ensure(f"harness-{folder.name}", from_base(folder.dockerfile, base)), base_id, arch
        except RuntimeError as e:
            raise InstallFailed(f"the image of {folder.name} is not there: {e}") from None

    async def _run(self, folder: HarnessFolder, tools: Path, image: str | None, log: Path) -> Outcome:
        """Run install.sh into `tools`, its output into `log`."""
        runtime = self.placement.runtime(image, read_only=(folder.path,), egress=folder.install.egress)
        with tempfile.TemporaryDirectory(dir=self.root, prefix=".home-") as scratch:
            env = {"HI_TOOLS": str(tools), "HI_HARNESS_DIR": str(folder.path),
                   "HOME": "/tmp" if self.placement.docker else scratch, "PATH": f"{tools}/bin:{self.placement.path}"}
            execution = await runtime.start(Spec(("bash", str(folder.path / "install.sh")), env=env, workspace=tools,
                                                 timeout_s=folder.install.timeout_s))
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


def describe(outcome: Outcome) -> str:
    if outcome.kind == "failed":
        return f"could not start: {outcome.reason}"
    if outcome.kind == "timed_out":
        return "ran out of time"
    return f"exited {outcome.code}" if outcome.code is not None else "was killed"
