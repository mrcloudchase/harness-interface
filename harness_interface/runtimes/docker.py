"""Layer 1: the Docker runtime. Every run gets a fresh container from its sandbox's image (built
once per Dockerfile), an internal network of its own, and an egress door on that network as its
only way out.

Its guarantees, on every run, whatever the Dockerfile says:
- no Linux capabilities, no privilege escalation, a read-only root, an unprivileged user: uid 1000
  when the server runs as root, or the server's own user otherwise, so the workspace is always its;
- process and memory limits, and the spec's timeout;
- no route out except tunnels to the allowed hosts; no DNS of its own;
- environment values passed by name, so no value is ever on a command line.

Paths are the same inside as outside: the workspace and any mounts appear at their own paths, so
nothing above this layer translates them. The workspace is writable; mounts are read-only.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..errors import Invalid
from ..execution import Execution, NeverStarted, Spec
from .egress import READY as DOOR_READY
from .egress import normalize
from .process import ProcessExecution

DOOR_IMAGE = "python:3.12-alpine"
DOOR_PORT = 3128
UID = 1000                                           # the sandbox user; it must own the workspace
# Every container, the door included: nothing to escalate with, nothing to write outside its mounts.
LOCKDOWN = ("--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only")
# The run's container, besides. /tmp allows exec, as a normal /tmp does: CLIs unpack native modules there.
HARDENING = (*LOCKDOWN, "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=512m", "--pids-limit", "512", "--memory", "4g")
PREFIX = "harness-"


@dataclass(frozen=True)
class Sandbox:
    """A Dockerfile, and the hosts its runs may reach besides those each run is given."""
    name: str
    dockerfile: str
    egress: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.dockerfile.strip():
            raise Invalid(f"sandbox '{self.name}' has an empty Dockerfile")
        object.__setattr__(self, "egress", tuple(self.egress))

    @property
    def tag(self) -> str:
        """The image's name: one per Dockerfile content, so a change builds a new image."""
        return f"harness-interface/{self.name}:{hashlib.sha256(self.dockerfile.encode()).hexdigest()[:12]}"


async def docker(*args: str, stdin: bytes | None = None) -> tuple[int, str]:
    """Run the Docker CLI; its exit code and its output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        raise RuntimeError("Docker is not installed") from None
    out, _ = await proc.communicate(stdin)
    return proc.returncode or 0, out.decode(errors="replace")


@dataclass(frozen=True)
class Names:
    """A run's containers and network, all named after it so a crash can be cleaned up by name."""
    run: str
    door: str
    network: str

    @classmethod
    def new(cls) -> Names:
        rid = uuid.uuid4().hex[:12]
        return cls(f"{PREFIX}run-{rid}", f"{PREFIX}door-{rid}", f"{PREFIX}net-{rid}")


class Docker:
    """The Docker engine as every run shares it: images, built once per Dockerfile, and recovery."""

    def __init__(self, build_logs: Path):
        self.build_logs = build_logs
        self._building: dict[str, asyncio.Lock] = {}

    async def image(self, sandbox: Sandbox) -> str:
        """The sandbox's image, built if this Dockerfile has not been built before."""
        tag = sandbox.tag
        async with self._building.setdefault(tag, asyncio.Lock()):
            if (await docker("image", "inspect", tag))[0] == 0:
                return tag
            with tempfile.TemporaryDirectory() as context:
                code, log = await docker("build", "-t", tag, "-f", "-", context, stdin=sandbox.dockerfile.encode())
            self.build_logs.mkdir(parents=True, exist_ok=True)
            (self.build_logs / f"build-{sandbox.name}-{tag.rsplit(':', 1)[1]}.log").write_text(log)
            if code != 0:
                raise RuntimeError(f"sandbox '{sandbox.name}' failed to build:\n{log[-2000:]}")
            return tag

    async def recover(self) -> None:
        """Remove the containers and networks of runs a crash cut off. Also the first sign of
        whether Docker is there at all."""
        code, out = await docker("ps", "-aq", "--filter", f"name={PREFIX}run-", "--filter", f"name={PREFIX}door-")
        if code != 0:
            raise RuntimeError(f"Docker is not reachable: {out.strip()}")
        if ids := out.split():
            await docker("rm", "-f", *ids)
        _, out = await docker("network", "ls", "-q", "--filter", f"name={PREFIX}net-")
        if ids := out.split():
            await docker("network", "rm", *ids)


class DockerRuntime:
    """Runs specs in fresh containers of one sandbox, each reaching only the allowed hosts."""

    def __init__(self, engine: Docker, sandbox: Sandbox, egress: Sequence[str] = (), mounts: Sequence[Path] = ()):
        self.engine, self.sandbox = engine, sandbox
        self.allowed = sorted({normalize(h) for h in (*sandbox.egress, *egress) if h.strip()})
        self.mounts = tuple(Path(m) for m in mounts)

    async def start(self, spec: Spec) -> Execution:
        try:
            # Shielded: a run cancelled during a build stops waiting, and the build finishes for the next.
            image = await asyncio.shield(self.engine.image(self.sandbox))
        except RuntimeError as e:
            return NeverStarted(str(e))
        names = Names.new()
        try:
            if spec.workspace:
                await asyncio.to_thread(hand_over, spec.workspace)   # a big workspace must not stall other runs
            for step in (("network", "create", "--internal", names.network),
                         self.door_argv(names),
                         ("network", "connect", "bridge", names.door)):
                code, out = await docker(*step)
                if code != 0:
                    raise RuntimeError(f"docker {step[0]} {step[1]} failed: {out[-500:]}")
            await door_ready(names)
            return await ProcessExecution.spawn(
                self.run_argv(spec, image, names), env={**os.environ, **spec.env}, cwd=None, input=spec.input,
                interactive=spec.interactive, timeout_s=spec.timeout_s,
                kill=lambda: docker("kill", names.run), cleanup=lambda: teardown(names))
        except asyncio.CancelledError:               # teardown is idempotent: whatever is left goes
            await asyncio.shield(teardown(names))
            raise
        except RuntimeError as e:
            await teardown(names)
            return NeverStarted(str(e))

    async def recover(self) -> None:
        await self.engine.recover()

    def run_argv(self, spec: Spec, image: str, names: Names) -> list[str]:
        proxy = f"http://{names.door}:{DOOR_PORT}"
        argv = ["docker", "run", "--rm", "-i", "--name", names.run, "--network", names.network, *HARDENING,
                "-e", f"HTTPS_PROXY={proxy}", "-e", f"HTTP_PROXY={proxy}"]
        if os.geteuid() != 0:                        # the workspace is the server user's: run as that user
            argv += ["--user", f"{os.getuid()}:{os.getgid()}"]
        if spec.workspace:
            argv += ["-v", f"{spec.workspace}:{spec.workspace}", "-w", str(spec.workspace)]
        for mount in self.mounts:
            argv += ["-v", f"{mount}:{mount}:ro"]
        for name in spec.env:                        # names only: the values travel in the Docker client's environment
            argv += ["-e", name]
        return [*argv, image, *spec.command]

    def door_argv(self, names: Names) -> tuple[str, ...]:
        script = str(Path(__file__).with_name("egress.py"))
        return ("run", "-d", "--rm", "--name", names.door, "--network", names.network, *LOCKDOWN,
                "-v", f"{script}:/door/egress.py:ro", DOOR_IMAGE,
                "python3", "/door/egress.py", f"0.0.0.0:{DOOR_PORT}", *self.allowed)


async def door_ready(names: Names, timeout_s: float = 10) -> None:
    """Wait for the door to accept connections: a run that calls out at once would otherwise find
    no way out."""
    out = ""
    for _ in range(int(timeout_s / 0.1)):
        code, out = await docker("logs", names.door)
        if DOOR_READY in out:
            return
        if code != 0:
            break
        await asyncio.sleep(0.1)
    raise RuntimeError(f"egress door did not start: {out[-500:]}")


def hand_over(workspace: Path) -> None:
    """Make the workspace the sandbox user's. A server running as root creates it as root, and the
    unprivileged user inside could not write to it; one running as a regular user is usually that
    uid already, and could not change it anyway."""
    if os.geteuid() != 0:
        return
    for root, dirs, files in os.walk(workspace):
        for name in (root, *(os.path.join(root, n) for n in dirs + files)):
            os.lchown(name, UID, UID)


async def teardown(names: Names) -> None:
    """Remove everything a run created. Each is gone already, or goes now."""
    await docker("rm", "-f", names.run, names.door)
    await docker("network", "rm", "-f", names.network)
