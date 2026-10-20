"""Layer 1: the Docker runtime. Every run gets a fresh container from the image it is given, an internal
network of its own, and an egress door on that network as its only way out.

Its guarantees, on every run, whatever the image holds:
- no Linux capabilities, no privilege escalation, a read-only root, process and memory limits, and
  an unprivileged user: uid 1000 when the server runs as root (it hands the writable paths over), or
  the server's own user otherwise, so what the run writes is always its own;
- tini as PID 1, so a stop (SIGINT) reaches the command's whole process group, and a kill follows;
- no route out but the door, which tunnels only to the hosts it is given, and no DNS of its own;
- at most one provider. Under the gateway the provider's key reaches only the door, on its stdin, and
  the run reads a session token from `KEY_PATH`; in file mode the run reads the key there. Either
  way the gateway's URL and the key's path are the same for every run, so a session can keep them;
- the spec's environment and nothing of the host's, passed by name so no value is on a command line
  (but PATH, HOME and DOCKER_*, which the Docker client runs by, and no secret ever is); the client
  itself gets only the allowlisted host variables;
- teardown of the container, the door, the network and the credential on every path, shielded.

Paths are the same inside as outside: the workspace and every mount appear at their own paths, so
nothing above this layer translates them. `Images` builds images from Dockerfiles, once each.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Sequence, TypeVar
from urllib.parse import urlsplit

from ..errors import Invalid
from ..execution import Execution, NeverStarted, Spec
from .door import APIS, DOOR_PORT, GATEWAY_PORT, READY, normalize
from .process import ProcessExecution, host_env

DOOR_IMAGE = "python:3.12-alpine"
DOOR_SCRIPT = Path(__file__).with_name("door.py")
DOOR_HOST, PROVIDER_HOST = "hi-door", "hi-provider"  # the door's aliases, the same on every run's network
GATEWAY = f"http://{PROVIDER_HOST}:{GATEWAY_PORT}"
PROXY = f"http://{DOOR_HOST}:{DOOR_PORT}"
NO_PROXY = f"127.0.0.1,localhost,{DOOR_HOST},{PROVIDER_HOST}"
KEY_PATH = Path("/run/hi/key")                       # where every run reads its credential
CA_PATH = "/etc/hi/ca.pem"                           # where a CA bundle appears, when one is given
CA_VARS = ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO")
SECRETS = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())   # memory, not disk
UID = 1000                                           # the sandbox user, when the server is root
PREFIX = "hi-"
# Every container, the door included: nothing to escalate with, nothing to write outside its mounts.
LOCKDOWN = ("--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--read-only")
# The run's container, besides. /tmp allows exec, as a normal /tmp does: CLIs unpack native modules there.
HARDENING = (*LOCKDOWN, "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=512m", "--pids-limit", "512", "--memory", "4g")
DOOR_LIMITS = ("--pids-limit", "64", "--memory", "256m")
T = TypeVar("T")


@dataclass(frozen=True)
class Provider:
    """The one model provider a run may call: its base URL, API shape and key, and how the key
    reaches the run (`gateway`: the session's token stands in for it; `file`: the key itself)."""
    url: str
    api: str
    key: str = field(repr=False)
    credential: str = "gateway"
    token: str = field(default="", repr=False)       # the session's, under the gateway

    def __post_init__(self) -> None:
        u = urlsplit(self.url)
        if u.scheme != "https" or not u.hostname:
            raise Invalid(f"a provider's URL must be https://host…: {self.url!r}")
        if self.api not in APIS:
            raise Invalid(f"a provider's API is one of {', '.join(APIS)}")
        if self.credential not in ("gateway", "file"):
            raise Invalid("a provider's credential is 'gateway' or 'file'")
        for name, value in (("key", self.key), ("token", self.token if self.credential == "gateway" else "-")):
            if not value or any(c in value for c in "\r\n\0"):
                raise Invalid(f"a provider's {name} must be one line")


def clients_own(name: str) -> bool:
    """A variable the Docker client itself runs by, so a run's value for it goes on the command line
    (none of them is a secret) and the client keeps the host's."""
    return name in ("PATH", "HOME") or name.startswith("DOCKER_")


def client_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """A Docker client's environment: the allowlisted host variables, with the rest of `env` for the
    container to take by name."""
    host = host_env()
    host.setdefault("DOCKER_CONFIG", str(Path.home() / ".docker"))   # never one a run's HOME could plant
    return {**host, **{k: v for k, v in (env or {}).items() if not clients_own(k)}}


def docker_bin() -> str:
    found = shutil.which("docker", path=host_env().get("PATH"))
    if not found:
        raise RuntimeError("Docker is not installed")
    return found


async def docker(*args: str, stdin: bytes | None = None) -> tuple[int, str]:
    """Run the Docker CLI; its exit code and its output."""
    proc = await asyncio.create_subprocess_exec(
        docker_bin(), *args, env=client_env(), stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await proc.communicate(stdin)
    except asyncio.CancelledError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass                                     # it had just ended
        raise
    return proc.returncode or 0, out.decode(errors="replace")


class Images:
    """Images built from Dockerfiles, each one once, named by its content so a change is a new image."""

    def __init__(self, logs: Path):
        self.logs = logs
        self._building: dict[str, asyncio.Lock] = {}

    @staticmethod
    def tag(name: str, dockerfile: str) -> str:
        return f"{PREFIX}{name}:{hashlib.sha256(dockerfile.encode()).hexdigest()[:12]}"

    async def ensure(self, name: str, dockerfile: str) -> str:
        """The image's tag, built first if this Dockerfile has not been built before."""
        tag = self.tag(name, dockerfile)
        async with self._building.setdefault(tag, asyncio.Lock()):
            if (await docker("image", "inspect", tag))[0] == 0:
                return tag
            with tempfile.TemporaryDirectory() as context:                 # an empty context: nothing to copy in
                code, log = await docker("build", "-t", tag, "-f", "-", context, stdin=dockerfile.encode())
            self.logs.mkdir(parents=True, exist_ok=True)
            (self.logs / f"build-{tag.replace(':', '-')}.log").write_text(log)
            if code != 0:
                raise RuntimeError(f"image {name} failed to build:\n{log[-2000:]}")
            return tag


@dataclass(frozen=True)
class Names:
    """A run's container, door, network and credential, named after it so a crash can be swept by name."""
    run: str
    door: str
    network: str
    secrets: Path

    @classmethod
    def new(cls) -> Names:
        rid = uuid.uuid4().hex[:12]
        return cls(f"{PREFIX}run-{rid}", f"{PREFIX}door-{rid}", f"{PREFIX}net-{rid}", SECRETS / f"{PREFIX}{rid}")


class DockerRuntime:
    """Runs specs in fresh containers of one image, each reaching only its provider and `egress`."""

    def __init__(self, image: str, *, read_only: Sequence[Path] = (), writable: Sequence[Path] = (),
                 egress: Sequence[str] = (), provider: Provider | None = None, ca_file: Path | None = None):
        self.image, self.provider, self.ca_file = image, provider, ca_file
        self.read_only, self.writable = tuple(Path(p) for p in read_only), tuple(Path(p) for p in writable)
        tunnels = [*egress, *([provider.url] if provider and provider.credential == "file" else [])]
        self.allowed = sorted({normalize(h) for h in tunnels if h.strip()})

    @property
    def provider_url(self) -> str | None:
        """The provider's base URL as the run must call it: the gateway's, at the same path, or its own."""
        if not self.provider:
            return None
        if self.provider.credential == "file":
            return self.provider.url
        return GATEWAY + urlsplit(self.provider.url).path.rstrip("/")

    @property
    def key_path(self) -> Path | None:
        """Where the run reads its credential: the session's token, or the key in file mode."""
        return KEY_PATH if self.provider else None

    async def start(self, spec: Spec) -> Execution:
        names, door = Names.new(), None
        try:
            run_bin = docker_bin()
            await whole(asyncio.to_thread(self._prepare, spec, names))   # a big workspace must not stall other runs
            await self._step("network", "create", "--internal", names.network)
            door = await self._spawn_door(names)
            await self._door_ready(door)
            await self._step("network", "connect", "bridge", names.door)
            env = {**spec.env, "HTTPS_PROXY": PROXY, "https_proxy": PROXY, "NO_PROXY": NO_PROXY, "no_proxy": NO_PROXY,
                   **({v: CA_PATH for v in CA_VARS} if self.ca_file else {})}
            return await ProcessExecution.spawn(
                [run_bin, *self.run_argv(spec, names, env)], env=client_env(env), cwd=None, input=spec.input,
                interactive=spec.interactive, timeout_s=spec.timeout_s,
                signal=lambda: interrupt(names.run), kill=lambda: docker("kill", names.run),
                cleanup=lambda: teardown(names, door), sidecars={"door": door.stdout})
        except asyncio.CancelledError:               # teardown is idempotent: whatever is left goes
            await asyncio.shield(teardown(names, door))
            raise
        except (RuntimeError, OSError) as e:
            await asyncio.shield(teardown(names, door))
            return NeverStarted(str(e) or repr(e))

    async def recover(self) -> None:
        await sweep()

    def run_argv(self, spec: Spec, names: Names, env: dict[str, str]) -> list[str]:
        user = f"{UID}:{UID}" if os.geteuid() == 0 else f"{os.getuid()}:{os.getgid()}"
        argv = ["run", "--rm", "-i", "--init", "-e", "TINI_KILL_PROCESS_GROUP=1", "--name", names.run,
                "--network", names.network, *HARDENING, "--user", user]
        if spec.workspace:
            argv += ["-v", f"{spec.workspace}:{spec.workspace}", "-w", str(spec.workspace)]
        for path in self.writable:
            argv += ["-v", f"{path}:{path}"]
        for path in self.read_only:
            argv += ["-v", f"{path}:{path}:ro"]
        if self.provider:
            argv += ["-v", f"{names.secrets / 'key'}:{KEY_PATH}:ro"]
        if self.ca_file:
            argv += ["-v", f"{self.ca_file}:{CA_PATH}:ro"]
        for name, value in env.items():              # names only: the values travel in the Docker client's environment
            argv += ["-e", f"{name}={value}" if clients_own(name) else name]
        return [*argv, self.image, *spec.command]

    def door_argv(self, names: Names) -> list[str]:
        argv = ["run", "-i", "--rm", "--name", names.door, "--network", names.network,
                "--network-alias", DOOR_HOST, "--network-alias", PROVIDER_HOST, *LOCKDOWN, *DOOR_LIMITS,
                "--user", "65534:65534", "-v", f"{DOOR_SCRIPT}:/door/door.py:ro"]
        if self.ca_file:
            argv += ["-v", f"{self.ca_file}:{CA_PATH}:ro", "-e", f"SSL_CERT_FILE={CA_PATH}"]
        argv += [DOOR_IMAGE, "python3", "/door/door.py", f"0.0.0.0:{DOOR_PORT}", *self.allowed]
        if self.provider and self.provider.credential == "gateway":
            argv += ["--gateway", f"0.0.0.0:{GATEWAY_PORT}", self.provider.url, self.provider.api]
        return argv

    def _prepare(self, spec: Spec, names: Names) -> None:
        """Hand the writable paths to the sandbox user, and write the run's credential."""
        if os.geteuid() == 0:
            for path in (*([spec.workspace] if spec.workspace else []), *self.writable):
                hand_over(path)
        if self.provider:
            names.secrets.mkdir(mode=0o700)
            key = names.secrets / "key"
            fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            with os.fdopen(fd, "w") as f:
                f.write(self.provider.token if self.provider.credential == "gateway" else self.provider.key)
            if os.geteuid() == 0:
                os.chown(key, UID, UID)

    async def _spawn_door(self, names: Names) -> asyncio.subprocess.Process:
        """Start the door, and give a gateway its token and key on stdin."""
        door = await asyncio.create_subprocess_exec(
            docker_bin(), *self.door_argv(names), env=client_env(), start_new_session=True,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        if self.provider and self.provider.credential == "gateway":
            door.stdin.write(f"{self.provider.token}\n{self.provider.key}\n".encode())
        door.stdin.close()
        return door

    @staticmethod
    async def _door_ready(door: asyncio.subprocess.Process) -> None:
        """Wait until the door listens: a run that calls out at once would otherwise find no way out."""
        said: list[str] = []
        try:
            async with asyncio.timeout(30):
                while (line := (await door.stdout.readline()).decode(errors="replace")) and line.strip() != READY:
                    said.append(line.strip())
        except TimeoutError:
            line = ""
        if not line:
            raise RuntimeError("egress door did not start: " + " | ".join(said[-5:]))

    @staticmethod
    async def _step(*args: str) -> None:
        code, out = await docker(*args)
        if code != 0:
            raise RuntimeError(f"docker {' '.join(args[:2])} failed: {out[-500:]}")


async def whole(awaitable: Awaitable[T]) -> T:
    """Await it to its end even if cancelled meanwhile, then let the cancel stand: a thread can't be
    stopped, and teardown must not race what it is still writing."""
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.wait([task])
        raise


async def interrupt(name: str) -> None:
    """SIGINT to a run's container, tried until it lands, so a stop asked for while the container is
    still being created is not lost. The run's end cancels it."""
    while (await docker("kill", "--signal", "INT", name))[0] != 0:
        await asyncio.sleep(0.05)


def hand_over(path: Path) -> None:
    """Make a tree the sandbox user's: a server running as root creates it as root, and the
    unprivileged user inside could not write to it."""
    for root, dirs, files in os.walk(path):
        for name in (root, *(os.path.join(root, n) for n in dirs + files)):
            os.lchown(name, UID, UID)


def shred(secrets: Path) -> None:
    """Overwrite a run's credential, then remove it."""
    key = secrets / "key"
    if key.exists():
        key.chmod(0o600)
        with open(key, "r+b") as f:
            f.write(b"\0" * max(key.stat().st_size, 64))
            f.flush()
            os.fsync(f.fileno())
        key.unlink()
    if secrets.exists():
        shutil.rmtree(secrets, ignore_errors=True)


async def teardown(names: Names, door: asyncio.subprocess.Process | None) -> None:
    """Remove everything a run created. Each is gone already, or goes now. The door's client goes
    first, so it can't create a door after the door is removed."""
    try:
        if door:
            try:
                door.kill()
            except ProcessLookupError:
                pass                                 # it ended already
            await door.wait()
        await docker("rm", "-f", names.run, names.door)
        await docker("network", "rm", "-f", names.network)
    except RuntimeError:
        pass                                         # no Docker: it made nothing
    finally:
        await asyncio.to_thread(shred, names.secrets)


async def sweep() -> None:
    """Remove the containers, networks and credentials of runs a crash cut off. Also the first sign
    of whether Docker is there at all."""
    code, out = await docker("ps", "-aq", "--filter", f"name=^{PREFIX}run-", "--filter", f"name=^{PREFIX}door-")
    if code != 0:
        raise RuntimeError(f"Docker is not reachable: {out.strip()}")
    if ids := out.split():
        await docker("rm", "-f", *ids)
    _, out = await docker("network", "ls", "-q", "--filter", f"name=^{PREFIX}net-")
    if ids := out.split():
        await docker("network", "rm", *ids)
    for secrets in SECRETS.glob(f"{PREFIX}" + "[0-9a-f]" * 12):
        await asyncio.to_thread(shred, secrets)
