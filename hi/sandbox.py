"""Where a harness runs. One interface, two runtimes.

Docker: the sandbox resource's image, on an internal network whose only other member is the
egress door, with the hardening every run gets, as an unprivileged user named after the harness.
gVisor when the host has it. Subprocess: the
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
UID = 1000                                           # every harness runs as this uid, under its own name
HARDENING = ["--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only",
             "--tmpfs", "/tmp:rw,size=512m", "--pids-limit", "512", "--memory", "4g"]


@dataclass(frozen=True)
class Job:
    id: str
    harness: str                                     # the container's hostname and user name
    prepared: Prepared
    workspace: Path
    harness_dir: Path
    log_path: Path
    spec: SandboxSpec
    egress: list[str]                                # host:port the run may reach


class Process(Protocol):
    timed_out: bool
    cancelled: bool
    async def chunks(self) -> AsyncIterator[bytes]: ...
    async def wait(self) -> int: ...
    def cancel(self) -> None: ...


class Sandbox(Protocol):
    runtime: str
    def mounts(self, job_workspace: Path, harness_dir: Path) -> Mounts: ...
    async def image(self, spec: SandboxSpec) -> str | None: ...
    async def start(self, job: Job) -> Process: ...


@dataclass
class _Proc:
    """One spawned process with a kill timer. Subclasses say how it is killed."""
    proc: asyncio.subprocess.Process
    out_path: Path
    timeout_s: int
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
    runtime = "local"

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir

    def mounts(self, workspace: Path, harness_dir: Path) -> Mounts:
        return Mounts(workspace=str(workspace), harness=str(harness_dir))

    async def image(self, spec: SandboxSpec) -> str | None:
        return None

    async def start(self, job: Job) -> Process:
        p = job.prepared
        proc = await _spawn(p.argv, {**os.environ, **p.env}, job.workspace, p.stdin, job.log_path)
        local = _LocalProc(proc, self.out_dir / f"{job.id}.out", p.timeout_s)
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
    def __init__(self, proc: asyncio.subprocess.Process, out_path: Path, timeout_s: int, names: "DockerNames"):
        super().__init__(proc, out_path, timeout_s)
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
    runtime = "docker"
    WORKSPACE, HARNESS = "/workspace", "/harness"

    def __init__(self, out_dir: Path, build_log_dir: Path):
        self.out_dir, self.build_log_dir = out_dir, build_log_dir
        self._locks: dict[str, asyncio.Lock] = {}
        self._runtimes: set[str] | None = None

    def mounts(self, workspace: Path, harness_dir: Path) -> Mounts:
        return Mounts(workspace=self.WORKSPACE, harness=self.HARNESS)

    # image
    @staticmethod
    def tag(spec: SandboxSpec) -> str:
        return f"hi/{spec.name}:{hashlib.sha256(spec.dockerfile.encode()).hexdigest()[:12]}"

    async def image(self, spec: SandboxSpec) -> str:
        """The image for this Dockerfile, built if this content has not been built before."""
        tag = self.tag(spec)
        async with self._locks.setdefault(tag, asyncio.Lock()):
            code, _ = await docker("image", "inspect", tag)
            if code == 0:
                return tag
            with tempfile.TemporaryDirectory() as context:
                code, log = await docker("build", "-t", tag, "-f", "-", context, stdin=spec.dockerfile.encode())
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
    def identity(self, job: Job) -> tuple[Path, Path]:
        """A passwd and a group file naming the harness as uid {UID}. Mounted over the image's own,
        they make `whoami`, `$USER` and the home directory the harness's, with no image per harness
        and no root inside the container."""
        passwd = self.out_dir / f"{job.id}.passwd"
        group = self.out_dir / f"{job.id}.group"
        passwd.write_text(f"root:x:0:0:root:/root:/bin/sh\n{job.harness}:x:{UID}:{UID}:{job.harness}:{self.WORKSPACE}/.home:/bin/bash\n")
        group.write_text(f"root:x:0:\n{job.harness}:x:{UID}:\n")
        return passwd, group

    def run_argv(self, job: Job, image: str, runtime: str, names: DockerNames) -> list[str]:
        p = job.prepared
        passwd, group = self.identity(job)
        argv = ["docker", "run", "--rm", "-i", "--name", names.run, "--hostname", job.harness,
                "--network", names.network, "--runtime", runtime, *HARDENING,
                "--user", f"{UID}:{UID}", "-v", f"{passwd}:/etc/passwd:ro", "-v", f"{group}:/etc/group:ro",
                "-e", f"USER={job.harness}", "-e", f"LOGNAME={job.harness}",
                "-v", f"{job.workspace}:{self.WORKSPACE}", "-v", f"{job.harness_dir}:{self.HARNESS}:ro", "-w", self.WORKSPACE,
                "-e", f"HTTPS_PROXY=http://{names.door}:{DOOR_PORT}", "-e", f"HTTP_PROXY=http://{names.door}:{DOOR_PORT}"]
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

    async def start(self, job: Job) -> Process:
        image, runtime, names = await self.image(job.spec), await self._runtime(job.spec), DockerNames.of(job.id)
        for step in (("network", "create", "--internal", names.network),
                     tuple(self.door_argv(names, job.egress)),
                     ("network", "connect", "bridge", names.door)):
            code, out = await docker(*step)
            if code != 0:
                await docker("rm", "-f", names.door)
                await docker("network", "rm", "-f", names.network)
                raise RuntimeError(f"docker {step[0]} {step[1]} failed: {out[-500:]}")
        argv = self.run_argv(job, image, runtime, names)
        proc = await _spawn(argv, {**os.environ, **job.prepared.env}, None, job.prepared.stdin, job.log_path)
        d = _DockerProc(proc, self.out_dir / f"{job.id}.out", job.prepared.timeout_s, names)
        d.arm()
        return d
