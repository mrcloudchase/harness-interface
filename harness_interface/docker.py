"""The Docker runtime. Every run: its sandbox's image, built once per Dockerfile; an internal
network of its own; the egress door on that network, its only way out; and the harness's
container on it, with the hardening every run gets.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .egress import READY as DOOR_READY
from .models import Sandbox
from .runner import Mounts
from .runtime import Job, Process, spawn

DOOR_IMAGE = "python:3.12-alpine"
DOOR_PORT = 3128
UID = 1000                                           # the sandbox user; it must own the workspace
# Every container, the door included: nothing to escalate with, nothing to write outside its mounts.
LOCKDOWN = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only"]
# The harness's container, besides. /tmp allows exec, as a normal /tmp does: CLIs unpack native
# modules there and load them.
HARDENING = [*LOCKDOWN, "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=512m", "--pids-limit", "512", "--memory", "4g"]
PREFIX = "harness-"


async def docker(*args: str, stdin: bytes | None = None) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec("docker", *args, stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError:
        raise RuntimeError("Docker is not installed. Install it, or set HI_RUNTIME=local.") from None
    out, _ = await proc.communicate(stdin)
    return proc.returncode or 0, out.decode(errors="replace")


@dataclass(frozen=True)
class DockerNames:
    run: str
    door: str
    network: str

    @classmethod
    def of(cls, job_id: str) -> "DockerNames":
        return cls(run=f"{PREFIX}run-{job_id}", door=f"{PREFIX}door-{job_id}", network=f"{PREFIX}net-{job_id}")


class DockerRuntime:
    name = "docker"
    WORKSPACE, HARNESS = "/workspace", "/harness"

    def __init__(self, build_log_dir: Path):
        self.build_log_dir = build_log_dir
        self._locks: dict[str, asyncio.Lock] = {}

    def mounts(self, workspace: Path, harness_dir: Path) -> Mounts:
        return Mounts(workspace=self.WORKSPACE, harness=self.HARNESS)

    # image
    @staticmethod
    def tag(sandbox: Sandbox) -> str:
        return f"harness-interface/{sandbox.name}:{hashlib.sha256(sandbox.dockerfile.encode()).hexdigest()[:12]}"

    async def image(self, sandbox: Sandbox) -> str:
        """The image for this Dockerfile, built if this content has not been built before."""
        tag = self.tag(sandbox)
        async with self._locks.setdefault(tag, asyncio.Lock()):
            code, _ = await docker("image", "inspect", tag)
            if code == 0:
                return tag
            with tempfile.TemporaryDirectory() as context:
                code, log = await docker("build", "-t", tag, "-f", "-", context, stdin=sandbox.dockerfile.encode())
            self.build_log_dir.mkdir(parents=True, exist_ok=True)
            (self.build_log_dir / f"build-{sandbox.name}-{tag.rsplit(':', 1)[1]}.log").write_text(log)
            if code != 0:
                raise RuntimeError(f"sandbox '{sandbox.name}' failed to build:\n{log[-2000:]}")
            return tag

    # run
    def run_argv(self, job: Job, names: DockerNames) -> list[str]:
        p = job.prepared
        argv = ["docker", "run", "--rm", "-i", "--name", names.run, "--network", names.network, *HARDENING,
                "-v", f"{job.workspace}:{self.WORKSPACE}", "-v", f"{job.harness_dir}:{self.HARNESS}:ro", "-w", self.WORKSPACE,
                "-e", f"HTTPS_PROXY=http://{names.door}:{DOOR_PORT}", "-e", f"HTTP_PROXY=http://{names.door}:{DOOR_PORT}"]
        for k in p.env:                              # names only: the values travel in the docker client's environment
            argv += ["-e", k]
        return [*argv, job.image, *p.argv]

    @staticmethod
    def door_argv(names: DockerNames, egress: list[str]) -> list[str]:
        door_script = str(Path(__file__).with_name("egress.py"))
        return ["run", "-d", "--rm", "--name", names.door, "--network", names.network, *LOCKDOWN,
                "-v", f"{door_script}:/door/egress.py:ro", DOOR_IMAGE,
                "python3", "/door/egress.py", f"0.0.0.0:{DOOR_PORT}", *egress]

    @staticmethod
    async def door_ready(names: DockerNames, timeout_s: float = 10) -> None:
        """Wait for the door to accept connections: a harness that calls its provider at once
        would otherwise find no way out."""
        out = ""
        for _ in range(int(timeout_s / 0.1)):
            code, out = await docker("logs", names.door)
            if DOOR_READY in out:
                return
            if code != 0:
                break
            await asyncio.sleep(0.1)
        raise RuntimeError(f"egress door did not start: {out[-500:]}")

    @staticmethod
    def hand_over(workspace: Path) -> None:
        """Make the workspace the sandbox user's. A server running as root creates it as root, and
        the unprivileged user inside could not write to it; a server running as a regular user
        is usually that uid already, and could not change it anyway."""
        if os.geteuid() != 0:
            return
        for root, dirs, files in os.walk(workspace):
            for name in (root, *(os.path.join(root, n) for n in dirs + files)):
                os.lchown(name, UID, UID)

    @staticmethod
    async def teardown(names: DockerNames) -> None:
        """Remove everything a run created. Each is gone already, or goes now."""
        await docker("rm", "-f", names.run, names.door)
        await docker("network", "rm", "-f", names.network)

    async def start(self, job: Job) -> Process:
        names = DockerNames.of(job.id)
        await asyncio.to_thread(self.hand_over, job.workspace)   # a big workspace must not stall other runs
        try:
            for step in (("network", "create", "--internal", names.network),
                         tuple(self.door_argv(names, job.egress)),
                         ("network", "connect", "bridge", names.door)):
                code, out = await docker(*step)
                if code != 0:
                    raise RuntimeError(f"docker {step[0]} {step[1]} failed: {out[-500:]}")
            await self.door_ready(names)
            proc = await spawn(self.run_argv(job, names), {**os.environ, **job.prepared.env}, None,
                               job.prepared.stdin)
        except BaseException:
            await self.teardown(names)
            raise

        def kill() -> None:
            asyncio.get_running_loop().create_task(docker("kill", names.run))
        return Process(proc, job.prepared.timeout_s, kill, lambda: self.teardown(names))

    async def recover(self) -> None:
        """At startup, remove the containers and networks of runs a restart cut off. Also the
        first sign of whether Docker is there at all."""
        code, out = await docker("ps", "-aq", "--filter", f"name={PREFIX}run-", "--filter", f"name={PREFIX}door-")
        if code != 0:
            raise RuntimeError(f"Docker is not reachable ({out.strip()}). Start it, or set HI_RUNTIME=local.")
        if ids := out.split():
            await docker("rm", "-f", *ids)
        _, out = await docker("network", "ls", "-q", "--filter", f"name={PREFIX}net-")
        if ids := out.split():
            await docker("network", "rm", *ids)
