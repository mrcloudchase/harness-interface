"""Where a harness runs. One interface, two runtimes.

Docker: the sandbox resource's image, on an internal network whose only other member is the
egress door, with the hardening every run gets. gVisor when the host has it. Subprocess: the
same contract on the host itself, for tests and for a laptop without Docker; no isolation and
no egress rule, and the record says so.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Protocol

from .models import Sandbox as SandboxSpec
from .runner import Mounts, Prepared

DOOR_IMAGE = "python:3.12-alpine"
DOOR_PORT = 3128
UID = 1000                                           # the sandbox user every image creates; it owns the workspace
HARDENING = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
             "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=512m", "--pids-limit", "512", "--memory", "4g"]


@dataclass(frozen=True)
class Job:
    id: str
    harness: str                                     # the container's hostname, and its user in the default image
    prepared: Prepared
    workspace: Path
    harness_dir: Path
    log_path: Path
    spec: SandboxSpec
    egress: list[str]                                # host:port the run may reach


class Process(Protocol):
    runtime: str                                     # what actually ran it: runsc, runc, or local
    timed_out: bool
    cancelled: bool
    async def chunks(self) -> AsyncIterator[bytes]: ...
    async def wait(self) -> int: ...
    def cancel(self) -> None: ...


class Sandbox(Protocol):
    def mounts(self, job_workspace: Path, harness_dir: Path) -> Mounts: ...
    async def image(self, spec: SandboxSpec, harness: str) -> str | None: ...
    async def start(self, job: Job) -> Process: ...


@dataclass
class _Proc:
    """One spawned process with a kill timer. Subclasses say how it is killed."""
    proc: asyncio.subprocess.Process
    out_path: Path
    timeout_s: int
    runtime: str
    timed_out: bool = False
    cancelled: bool = False
    _timer: asyncio.TimerHandle | None = field(default=None, repr=False)

    def arm(self) -> None:
        self._timer = asyncio.get_running_loop().call_later(self.timeout_s, self._end, "timeout")

    async def chunks(self) -> AsyncIterator[bytes]:
        assert self.proc.stdout
        with open(self.out_path, "wb") as out:
            while chunk := await self.proc.stdout.read(65536):
                out.write(chunk)
                yield chunk

    async def wait(self) -> int:
        code = await self.proc.wait()
        if self._timer:
            self._timer.cancel()
        await self.cleanup()
        return code

    def cancel(self) -> None:
        self._end("cancelled")

    def _end(self, why: str) -> None:
        if self.proc.returncode is not None:
            return
        setattr(self, "timed_out" if why == "timeout" else "cancelled", True)
        self.kill()

    def kill(self) -> None: ...
    async def cleanup(self) -> None: ...


async def _spawn(argv: list[str], env: dict[str, str], cwd: Path | None, stdin: bytes, log_path: Path) -> asyncio.subprocess.Process:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "wb") as log:
        proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.PIPE, stderr=log, start_new_session=True)
    assert proc.stdin
    proc.stdin.write(stdin)
    await proc.stdin.drain()
    proc.stdin.close()
    return proc


# ── subprocess ──────────────────────────────────────────────────────────────────────────────────
class _LocalProc(_Proc):
    def kill(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class LocalSandbox:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir

    def mounts(self, workspace: Path, harness_dir: Path) -> Mounts:
        return Mounts(workspace=str(workspace), harness=str(harness_dir))

    async def image(self, spec: SandboxSpec, harness: str) -> str | None:
        return None

    async def start(self, job: Job) -> Process:
        p = job.prepared
        proc = await _spawn(p.argv, {**os.environ, **p.env}, job.workspace, p.stdin, job.log_path)
        local = _LocalProc(proc, self.out_dir / f"{job.id}.out", p.timeout_s, "local")
        local.arm()
        return local


# ── docker ──────────────────────────────────────────────────────────────────────────────────────
async def docker(*args: str, stdin: bytes | None = None, env: dict[str, str] | None = None) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec("docker", *args, stdin=asyncio.subprocess.PIPE if stdin is not None else None,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                env={**os.environ, **(env or {})})
    out, _ = await proc.communicate(stdin)
    return proc.returncode or 0, out.decode(errors="replace")


class _DockerProc(_Proc):
    def __init__(self, proc: asyncio.subprocess.Process, out_path: Path, timeout_s: int, runtime: str, names: "DockerNames"):
        super().__init__(proc, out_path, timeout_s, runtime)
        self.names = names

    def kill(self) -> None:
        asyncio.get_running_loop().create_task(docker("kill", self.names.run))

    async def cleanup(self) -> None:
        await docker("rm", "-f", self.names.door)
        await docker("network", "rm", "-f", self.names.network)


@dataclass(frozen=True)
class DockerNames:
    run: str
    door: str
    network: str

    @classmethod
    def of(cls, job_id: str) -> "DockerNames":
        return cls(run=f"hi-run-{job_id}", door=f"hi-door-{job_id}", network=f"hi-net-{job_id}")


class DockerSandbox:
    """Every run: one internal network, one door on it, one container on it."""
    WORKSPACE, HARNESS = "/workspace", "/harness"

    def __init__(self, out_dir: Path, build_log_dir: Path):
        self.out_dir, self.build_log_dir = out_dir, build_log_dir
        self._locks: dict[str, asyncio.Lock] = {}
        self._runtimes: set[str] | None = None

    def mounts(self, workspace: Path, harness_dir: Path) -> Mounts:
        return Mounts(workspace=self.WORKSPACE, harness=self.HARNESS)

    # image
    @staticmethod
    def dockerfile(spec: SandboxSpec, harness: str) -> str:
        """`{harness}` in a Dockerfile is the harness's name: the default image makes it the user."""
        return spec.dockerfile.replace("{harness}", harness)

    @classmethod
    def tag(cls, spec: SandboxSpec, harness: str) -> str:
        """Tagged by the rendered content: a Dockerfile that names the harness gets one image per
        harness, one that does not is shared by all of them."""
        return f"hi/{spec.name}:{hashlib.sha256(cls.dockerfile(spec, harness).encode()).hexdigest()[:12]}"

    async def image(self, spec: SandboxSpec, harness: str) -> str:
        """The image for this Dockerfile, built if this content has not been built before."""
        tag = self.tag(spec, harness)
        async with self._locks.setdefault(tag, asyncio.Lock()):
            code, _ = await docker("image", "inspect", tag)
            if code == 0:
                return tag
            with tempfile.TemporaryDirectory() as context:
                code, log = await docker("build", "-t", tag, "-f", "-", context, stdin=self.dockerfile(spec, harness).encode())
            self.build_log_dir.mkdir(parents=True, exist_ok=True)
            (self.build_log_dir / f"build-{spec.name}-{tag.rsplit(':', 1)[1]}.log").write_text(log)
            if code != 0:
                raise RuntimeError(f"sandbox '{spec.name}' failed to build:\n{log[-2000:]}")
            return tag

    async def _runtime(self, spec: SandboxSpec) -> str:
        if spec.runtime != "auto":
            return spec.runtime
        if self._runtimes is None:
            code, out = await docker("info", "--format", "{{json .Runtimes}}")
            try:
                self._runtimes = set(json.loads(out)) if code == 0 else set()
            except ValueError:
                self._runtimes = set()
        return "runsc" if "runsc" in self._runtimes else "runc"

    # run
    def run_argv(self, job: Job, image: str, runtime: str, names: DockerNames, door_ip: str) -> list[str]:
        p = job.prepared
        argv = ["docker", "run", "--rm", "-i", "--name", names.run, "--hostname", job.harness,
                "--network", names.network, "--runtime", runtime, *HARDENING,
                "-v", f"{job.workspace}:{self.WORKSPACE}", "-v", f"{job.harness_dir}:{self.HARNESS}:ro", "-w", self.WORKSPACE,
                # by address, not name: Docker's DNS for container names does not work under gVisor
                "-e", f"HTTPS_PROXY=http://{door_ip}:{DOOR_PORT}", "-e", f"HTTP_PROXY=http://{door_ip}:{DOOR_PORT}"]
        for k in p.env:                              # names only: the values travel in the docker client's environment
            argv += ["-e", k]
        return [*argv, image, *p.argv]

    @staticmethod
    def door_argv(names: DockerNames, egress: list[str]) -> list[str]:
        door_script = str(Path(__file__).with_name("egress.py"))
        return ["run", "-d", "--rm", "--name", names.door, "--network", names.network,
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
                "-v", f"{door_script}:/door/egress.py:ro", DOOR_IMAGE,
                "python3", "/door/egress.py", f"0.0.0.0:{DOOR_PORT}", *egress]

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

    async def start(self, job: Job) -> Process:
        image, runtime, names = await self.image(job.spec, job.harness), await self._runtime(job.spec), DockerNames.of(job.id)
        self.hand_over(job.workspace)
        for step in (("network", "create", "--internal", names.network),
                     tuple(self.door_argv(names, job.egress)),
                     ("network", "connect", "bridge", names.door)):
            code, out = await docker(*step)
            if code != 0:
                await docker("rm", "-f", names.door)
                await docker("network", "rm", "-f", names.network)
                raise RuntimeError(f"docker {step[0]} {step[1]} failed: {out[-500:]}")
        _, door_ip = await docker("inspect", "-f", f'{{{{(index .NetworkSettings.Networks "{names.network}").IPAddress}}}}', names.door)
        argv = self.run_argv(job, image, runtime, names, door_ip.strip())
        proc = await _spawn(argv, {**os.environ, **job.prepared.env}, None, job.prepared.stdin, job.log_path)
        d = _DockerProc(proc, self.out_dir / f"{job.id}.out", job.prepared.timeout_s, runtime, names)
        d.arm()
        return d
