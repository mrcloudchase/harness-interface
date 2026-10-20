#!/usr/bin/env python3
"""hirun: prototype runner for harness folders. The candidate execution contract, nothing more.

    hirun.py base                          build the base image (tag = hash of base.Dockerfile)
    hirun.py check   <folder>              validate harness.json and the hi_adapter.py copy
    hirun.py install <folder> [--local]    cached install -> tools/<name>-<hash>/
    hirun.py run     <folder> --task T [options]   one response; prints a result JSON
    hirun.py clean                         remove leftovers of crashed runs (hi-* containers, networks, keys)

Stdlib only; reuses LOCKDOWN/HARDENING/UID from harness_interface.runtimes.docker and the egress
Door (via door.py). Every container and network is named hi-*-<sid>; everything goes at teardown.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, "/home/user/harness-interface")
from harness_interface.runtimes.docker import HARDENING, LOCKDOWN, UID  # noqa: E402
from harness_interface.runtimes.egress import READY, normalize  # noqa: E402

ROOT = Path(__file__).resolve().parent
TOOLS, WORK = ROOT / "tools", ROOT / "work"
CANON_ADAPTER = ROOT / "template" / "hi_adapter.py"
EGRESS_PY = Path("/home/user/harness-interface/harness_interface/runtimes/egress.py")
DOOR_IMAGE, DOOR_PORT, GATEWAY_PORT = "python:3.12-alpine", 3128, 8080
CA_IN = "/etc/hi/ca.pem"                               # where a host CA bundle appears in containers
CA_VARS = ("SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "GIT_SSL_CAINFO")
APIS = ("anthropic-messages", "openai-responses", "openai-chat")
INTERRUPTS = ("steered", "continued", "responded")
# The only host variables a child (docker client or local harness) inherits: an allowlist, so no
# stray credential (CLAUDE*, *_API_KEY, tokens) ever reaches a harness or a docker client's environ.
PASS_ENV = re.compile(r"^(PATH|HOME|LANG|LC_\w+|TERM|TZ|USER|LOGNAME|HTTPS?_PROXY|https?_proxy|NO_PROXY|no_proxy|"
                      r"SSL_CERT_FILE|SSL_CERT_DIR|NODE_EXTRA_CA_CERTS|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE|"
                      r"GIT_SSL_CAINFO|DOCKER_HOST|DOCKER_CONFIG|DOCKER_CONTEXT)$")
SYS_PATH = "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"


def die(msg: str) -> None:
    raise SystemExit(f"hirun: {msg}")


def say(msg: str) -> None:
    print(f"hirun: {msg}", file=sys.stderr, flush=True)


def docker(*args: str, input: bytes | None = None, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=input, capture_output=True, timeout=timeout, env=host_env())


def host_env() -> dict:
    """The part of the runner's environment a child may inherit (PASS_ENV)."""
    return {k: v for k, v in os.environ.items() if PASS_ENV.match(k)}


def host_ca() -> str | None:
    """The machine's CA bundle, when its egress re-signs TLS (this sandbox does); else None."""
    ca = os.environ.get("HI_CA_FILE", "/root/.ccr/ca-bundle.crt")
    return ca if ca and os.path.isfile(ca) else None


# --- the folder ----------------------------------------------------------------------------------
class Folder:
    """A harness folder, validated: unknown or missing fields are errors, not defaults."""
    TOP = {"name", "description", "provider", "apis", "install", "files", "run"}
    RUN = {"interrupt", "stdout", "timeout_s", "stop_timeout_s"}

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        spec = json.loads((self.path / "harness.json").read_text())
        self.problems = self.validate(spec)
        if self.problems:
            die(f"{self.path}/harness.json: " + "; ".join(self.problems))
        self.spec, self.name, self.run = spec, spec["name"], spec["run"]
        self.install_sh = (self.path / "install.sh").read_bytes()

    def validate(self, s: dict) -> list[str]:
        p = [f"unknown field {k}" for k in set(s) - self.TOP] + [f"missing {k}" for k in self.TOP - set(s)]
        if p:
            return p
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", s["name"]):
            p.append("name must be [a-z0-9-]")
        if not (isinstance(s["apis"], list) and s["apis"] and set(s["apis"]) <= set(APIS)):
            p.append(f"apis must be a non-empty subset of {APIS}")
        prov = s["provider"]
        if set(prov) != {"url", "api"} or not prov["url"].startswith("https://") or prov["api"] not in s["apis"]:
            p.append("provider must be {url: https://…, api: one of apis}")
        inst = s["install"]
        if set(inst) != {"egress", "timeout_s"} or not isinstance(inst["egress"], list) or inst["timeout_s"] <= 0:
            p.append("install must be {egress: [host…], timeout_s: >0}")
        for f in s["files"]:
            if f.startswith("/") or ".." in Path(f).parts:
                p.append(f"files: {f} must be relative to the workspace")
        r = s["run"]
        if set(r) != self.RUN:
            p.append(f"run must have exactly {sorted(self.RUN)}")
        elif r["interrupt"] not in INTERRUPTS or r["timeout_s"] <= 0 or r["stop_timeout_s"] <= 0:
            p.append(f"run.interrupt in {INTERRUPTS}; timeouts > 0")
        for f in ("install.sh", "run.sh", "adapter.py", "hi_adapter.py"):
            if not (self.path / f).is_file():
                p.append(f"missing {f}")
        return p

    def check_adapter(self) -> bool:
        return (self.path / "hi_adapter.py").read_bytes() == CANON_ADAPTER.read_bytes()


# --- base image and tools cache ------------------------------------------------------------------
class Base:
    dockerfile = ROOT / "base.Dockerfile"

    @property
    def tag(self) -> str:
        return "hi-base:" + hashlib.sha256(self.dockerfile.read_bytes()).hexdigest()[:12]

    def image_id(self, build: bool = True) -> str:
        r = docker("image", "inspect", "-f", "{{.Id}}", self.tag)
        if r.returncode != 0 and build:
            say(f"building {self.tag}")
            ctx = WORK / "empty-context"
            ctx.mkdir(parents=True, exist_ok=True)
            b = docker("build", "-t", self.tag, "-f", str(self.dockerfile), str(ctx), timeout=1200)
            if b.returncode != 0:
                die(f"base build failed:\n{b.stderr.decode()[-2000:]}")
            r = docker("image", "inspect", "-f", "{{.Id}}", self.tag)
        if r.returncode != 0:
            die(f"no base image {self.tag}")
        return r.stdout.decode().strip()


def chown_tree(path: Path) -> None:
    """Hand a tree to the sandbox user (the runner is root; uid 1000 must write it)."""
    if os.geteuid() == 0:
        for root, dirs, files in os.walk(path):
            for n in (root, *(os.path.join(root, x) for x in dirs + files)):
                os.lchown(n, UID, UID)


class Tools:
    """tools/<name>-<hash>/: hash = install.sh + base image id (+ 'local' for a host install).
    Complete only once `.hi-installed` exists; a failed or interrupted install leaves nothing."""

    def __init__(self, folder: Folder, local: bool):
        self.folder, self.local = folder, local
        self.base_id = "local" if local else Base().image_id()
        h = hashlib.sha256(folder.install_sh + b"\0" + self.base_id.encode()).hexdigest()[:12]
        self.dir = TOOLS / f"{folder.name}-{'local-' if local else ''}{h}"

    def ensure(self) -> tuple[Path, bool]:
        TOOLS.mkdir(parents=True, exist_ok=True)
        with open(TOOLS / f".{self.dir.name}.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (self.dir / ".hi-installed").exists():
                return self.dir, True
            shutil.rmtree(self.dir, ignore_errors=True)
            self.dir.mkdir()
            t0, log = time.time(), self.dir.with_suffix(".install.log")
            try:
                code = self._local(log) if self.local else self._docker(log)
            except subprocess.TimeoutExpired:
                code = "timeout"
            if code != 0:
                shutil.rmtree(self.dir, ignore_errors=True)
                die(f"install of {self.folder.name} failed ({code}); log: {log}")
            (self.dir / ".hi-installed").write_text(json.dumps(
                {"harness": self.folder.name, "base_image": self.base_id, "seconds": round(time.time() - t0, 1),
                 "install_sha256": hashlib.sha256(self.folder.install_sh).hexdigest()}))
            return self.dir, False

    def _env(self) -> dict:
        return {"HI_TOOLS": str(self.dir), "HI_HARNESS_DIR": str(self.folder.path)}

    def _local(self, log: Path) -> int:
        env = {**host_env(), **self._env(), "HOME": str(WORK / "install-home"),
               "PATH": f"{self.dir}/bin:{os.environ['PATH']}"}
        with open(log, "wb") as f:
            return subprocess.run(["bash", str(self.folder.path / "install.sh")], env=env, cwd=self.dir, stdout=f,
                                  stderr=subprocess.STDOUT, timeout=self.folder.spec["install"]["timeout_s"]).returncode

    def _docker(self, log: Path) -> int:
        chown_tree(self.dir)
        sid = "i" + uuid.uuid4().hex[:11]
        with Network(sid, self.folder.spec["install"]["egress"]) as net:
            argv = ["run", "--rm", "--name", f"hi-install-{sid}", "--network", net.name, "--init", *HARDENING,
                    "--user", f"{UID}:{UID}", "-v", f"{self.folder.path}:{self.folder.path}:ro",
                    "-v", f"{self.dir}:{self.dir}", "-w", "/tmp", *ca_args()]
            env = {**self._env(), "HOME": "/tmp", "PATH": f"{self.dir}/bin:{SYS_PATH}", **net.proxy_env()}
            for k, v in env.items():
                argv += ["-e", f"{k}={v}"]              # no secrets here, so values may be on argv
            r = docker(*argv, Base().tag, "bash", str(self.folder.path / "install.sh"),
                       timeout=self.folder.spec["install"]["timeout_s"])
            log.write_bytes(r.stdout + r.stderr + ("\n--- door ---\n" + "\n".join(net.door_log)).encode())
            return r.returncode


def ca_args() -> list[str]:
    ca = host_ca()
    if not ca:
        return []
    return ["-v", f"{ca}:{CA_IN}:ro", *(x for v in CA_VARS for x in ("-e", f"{v}={CA_IN}"))]


# --- network, door and secrets -------------------------------------------------------------------
class Network:
    """An --internal network and its door container: the only way out. With a gateway, the door
    also serves the provider on :8080 and gets the real key on its stdin (never argv/env/disk)."""

    def __init__(self, sid: str, allowed: list[str], gateway: tuple[str, str, str, str] | None = None):
        self.sid, self.allowed, self.gateway = sid, sorted({normalize(h) for h in allowed if h}), gateway
        self.name, self.door = f"hi-net-{sid}", f"hi-door-{sid}"
        self.door_log: list[str] = []
        self.proc: subprocess.Popen | None = None

    def proxy_env(self) -> dict:
        proxy, no = f"http://{self.door}:{DOOR_PORT}", f"127.0.0.1,localhost,{self.door}"
        return {"HTTPS_PROXY": proxy, "https_proxy": proxy, "NO_PROXY": no, "no_proxy": no}

    def gateway_url(self, upstream: str) -> str:
        path = re.sub(r"^https://[^/]+", "", upstream)
        return f"http://{self.door}:{GATEWAY_PORT}{path}"

    def __enter__(self) -> Network:
        try:
            self._start()
        except BaseException:
            self.__exit__()
            raise
        return self

    def _start(self) -> None:
        if docker("network", "create", "--internal", self.name).returncode != 0:
            die(f"cannot create network {self.name}")
        argv = ["docker", "run", "-i", "--rm", "--name", self.door, "--network", self.name, *LOCKDOWN,
                "--user", "65534:65534", "-v", f"{EGRESS_PY}:/door/egress.py:ro",
                "-v", f"{ROOT / 'door.py'}:/door/door.py:ro"]
        tail = []
        if self.gateway:
            upstream, api = self.gateway[0], self.gateway[1]
            argv += ca_args()
            tail = ["--gateway", f"0.0.0.0:{GATEWAY_PORT}", upstream, api]
        argv += [DOOR_IMAGE, "python3", "/door/door.py", f"0.0.0.0:{DOOR_PORT}", *self.allowed, *tail]
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     env=host_env())
        if self.gateway:
            token, key = self.gateway[2], self.gateway[3]
            self.proc.stdin.write(f"{token}\n{key}\n".encode())
        self.proc.stdin.close()
        ready = threading.Event()

        def read():
            for raw in self.proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                self.door_log.append(line)
                if line == READY:
                    ready.set()
        threading.Thread(target=read, daemon=True).start()
        if not ready.wait(20):
            die(f"door did not start: {self.door_log[-5:]}")
        if docker("network", "connect", "bridge", self.door).returncode != 0:
            die("cannot connect the door to the bridge")

    def __exit__(self, *_exc) -> None:
        docker("rm", "-f", self.door)
        docker("network", "rm", self.name)
        if self.proc:
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Secret:
    """How the provider key reaches the harness.
    env:     HI_PROVIDER_KEY by name (value only in the docker client's / process's environment).
    file:    HI_PROVIDER_KEY_FILE -> /dev/shm/hi-<sid>/key, 0400, owner uid 1000, mounted read-only.
    gateway: the same file holds a per-session placeholder token; HI_PROVIDER_URL points at the
             door's gateway, which swaps the token for the key. The key never enters the sandbox."""

    def __init__(self, mode: str, sid: str, key: str, api: str):
        self.mode, self.key = mode, key
        self.token = None                              # shaped like a real key, for CLIs that check
        if mode == "gateway":
            self.token = ("sk-ant-api03-hi-" if api == "anthropic-messages" else "sk-hi-") + secrets.token_hex(24)
        self.dir = Path(f"/dev/shm/hi-{sid}")
        self.file = self.dir / "key"

    def __repr__(self) -> str:
        return f"Secret({self.mode})"

    def setup(self, docker_mode: bool) -> dict:
        """The contract env for the harness; writes the key file when there is one."""
        if self.mode == "env":
            return {"HI_PROVIDER_KEY": self.key}
        self.dir.mkdir(mode=0o700)
        fd = os.open(self.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(fd, "w") as f:
            f.write(self.token or self.key)
        if docker_mode and os.geteuid() == 0:
            os.chown(self.file, UID, UID)
            os.chown(self.dir, UID, UID)
        return {"HI_PROVIDER_KEY_FILE": str(self.file)}

    def mounts(self) -> list[str]:
        return [] if self.mode == "env" else ["-v", f"{self.file}:{self.file}:ro"]

    def teardown(self) -> None:
        if self.file.exists():
            os.chmod(self.file, 0o600)
            with open(self.file, "r+b") as f:             # overwrite, then unlink
                f.write(b"\0" * max(len(self.key), 64))
            self.file.unlink()
        if self.dir.exists():
            self.dir.rmdir()


class LocalGateway:
    """The gateway on host loopback, for --local --secret gateway."""

    def __init__(self, upstream: str, api: str, token: str, key: str):
        import asyncio
        sys.path.insert(0, str(ROOT))
        from door import Gateway
        self.loop = asyncio.new_event_loop()
        self.server = self.loop.run_until_complete(
            asyncio.start_server(Gateway(upstream, api, token, key).handle, "127.0.0.1", 0, ))
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}" + re.sub(r"^https://[^/]+", "", upstream)
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.server.close)


# --- one response --------------------------------------------------------------------------------
def snapshot(ws: Path) -> dict[str, str]:
    """path -> content hash, for every file outside .home."""
    out = {}
    for root, dirs, files in os.walk(ws):
        if Path(root) == ws:
            dirs[:] = [d for d in dirs if d != ".home"]
        for n in files:
            p = Path(root, n)
            try:
                out[str(p.relative_to(ws))] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            except OSError:
                pass
    return out


class Run:
    """Prepare the workspace, start the harness, stream it, steer/stop/kill on cue, collect."""

    def __init__(self, folder: Folder, a: argparse.Namespace):
        self.f, self.a = folder, a
        self.sid = time.strftime("%H%M%S") + uuid.uuid4().hex[:6]
        self.docker = not a.local
        self.ws = Path(a.workspace or WORK / f"ws-{self.sid}").resolve()
        self.rundir = WORK / "runs" / self.sid
        self.lines = 0
        self.steers_sent = 0
        self.stop_reason: str | None = None
        self.stop_at: float | None = None
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.net: Network | None = None
        self.secret: Secret | None = None
        self.gw: LocalGateway | None = None

    # preparing
    def prepare(self) -> dict:
        self.ws.mkdir(parents=True, exist_ok=True)
        self.rundir.mkdir(parents=True)
        home = self.ws / ".home"
        home.mkdir(exist_ok=True)
        if (self.f.path / "home").is_dir():
            shutil.copytree(self.f.path / "home", home, dirs_exist_ok=True)
        for rel, template in self.f.spec["files"].items():
            content = template.replace("{instructions}", self.a.instructions)
            if content.strip():
                (self.ws / rel).parent.mkdir(parents=True, exist_ok=True)
                (self.ws / rel).write_text(content)
        if self.docker:
            chown_tree(self.ws)
            chown_tree(self.rundir)
        return {"task": self.a.task, "instructions": self.a.instructions, "model": self.a.model,
                "resume": self.a.resume, "metadata": {}}

    def contract_env(self, tools: Path) -> dict:
        env = {"HI_MODEL": self.a.model, "HI_RESUME": self.a.resume or "", "HI_WORKSPACE": str(self.ws),
               "HI_HARNESS_DIR": str(self.f.path), "HI_TOOLS": str(tools), "HI_OUTPUT": str(self.rundir / "output.json"),
               "HOME": str(self.ws / ".home"), "PATH": f"{tools}/bin:{SYS_PATH if self.docker else os.environ['PATH']}"}
        if self.a.key_file:
            prov = self.f.spec["provider"]
            url, api = self.a.provider_url or prov["url"], self.a.provider_api or prov["api"]
            if api not in self.f.spec["apis"]:
                die(f"{self.f.name} does not speak {api}")
            key = Path(self.a.key_file).read_text().strip()
            self.secret = Secret(self.a.secret, self.sid, key, api)
            env.update(self.secret.setup(self.docker), HI_PROVIDER_API=api, HI_PROVIDER_URL=url)
            if self.a.secret == "gateway":
                if self.docker:
                    self.net = Network(self.sid, [], (url, api, self.secret.token, key))
                    env["HI_PROVIDER_URL"] = self.net.gateway_url(url)
                else:
                    self.gw = LocalGateway(url, api, self.secret.token, key)
                    env["HI_PROVIDER_URL"] = self.gw.url
            elif self.docker:
                self.net = Network(self.sid, [url])
        if self.docker:
            self.net = self.net or Network(self.sid, [])
            self.net.__enter__()
            env.update(self.net.proxy_env())
        else:
            env["NO_PROXY"] = env["no_proxy"] = "127.0.0.1,localhost"
        return env

    # running
    def start(self, env: dict) -> None:
        run_sh = str(self.f.path / "run.sh")
        if self.docker:
            argv = ["docker", "run", "--rm", "-i", "--name", f"hi-run-{self.sid}", "--network", self.net.name,
                    "--init", "-e", "TINI_KILL_PROCESS_GROUP=1", *HARDENING, "--user", f"{UID}:{UID}",
                    "-v", f"{self.ws}:{self.ws}", "-v", f"{self.f.path}:{self.f.path}:ro",
                    "-v", f"{env['HI_TOOLS']}:{env['HI_TOOLS']}:ro", "-v", f"{self.rundir}:{self.rundir}",
                    *(self.secret.mounts() if self.secret else []), *ca_args(), "-w", str(self.ws)]
            for name in env:
                argv += ["-e", name]                    # names only: values travel in the client's env
            argv += [Base().tag, "bash", run_sh]
            self.proc = subprocess.Popen(argv, env={**host_env(), **env}, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        else:
            self.proc = subprocess.Popen(["bash", run_sh], env={**host_env(), **env}, cwd=self.ws,
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         start_new_session=True)

    def interrupt(self) -> None:
        if self.docker:
            docker("kill", "--signal", "INT", f"hi-run-{self.sid}")
        else:
            os.killpg(self.proc.pid, signal.SIGINT)

    def kill(self) -> None:
        if self.docker:
            docker("kill", f"hi-run-{self.sid}")
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def stop(self, why: str) -> None:
        """SIGINT (graceful), then a kill after run.stop_timeout_s."""
        with self.lock:
            if self.stop_reason:
                return
            self.stop_reason = why
        say(f"stop ({why}): SIGINT")
        self.stop_at = time.monotonic()
        self.interrupt()
        t = threading.Timer(self.f.run["stop_timeout_s"], self._kill_if_alive)
        t.daemon = True
        t.start()

    def _kill_if_alive(self) -> None:
        if self.proc.poll() is None:
            say("stop timeout: kill")
            self.stop_reason = (self.stop_reason or "") + "+killed"
            self.kill()

    def steer(self, text: str) -> None:
        try:
            self.proc.stdin.write((json.dumps(text) + "\n").encode())
            self.proc.stdin.flush()
            self.steers_sent += 1
            say(f"steer sent: {text!r}")
        except (BrokenPipeError, ValueError):
            say("steer not sent: stdin closed")

    def on_stdout_line(self) -> None:
        self.lines += 1
        a = self.a
        for n, text in a.steer_after_lines or []:
            if self.lines == int(n):
                self.steer(text)
        if a.stop_after_lines and self.lines == a.stop_after_lines:
            self.stop("requested")
        if a.kill_after_lines and self.lines == a.kill_after_lines:
            say("hard kill (no SIGINT)")
            self.stop_reason = "killed"
            self.kill()

    def pump(self, stream, name: str) -> None:
        with open(self.rundir / f"{name}.log", "wb") as log:
            for raw in stream:
                log.write(raw)
                log.flush()
                if not self.a.quiet:
                    sys.stderr.write(f"[{name}] {raw.decode(errors='replace')}")
                if name == "stdout":
                    self.on_stdout_line()

    def execute(self) -> dict:
        tools, _ = Tools(self.f, self.a.local).ensure()
        t0 = time.time()
        request = self.prepare()
        before = snapshot(self.ws)
        try:
            env = self.contract_env(tools)
            self.start(env)
            self.proc.stdin.write((json.dumps(request, separators=(",", ":")) + "\n").encode())
            self.proc.stdin.flush()
            pumps = [threading.Thread(target=self.pump, args=(s, n), daemon=True)
                     for s, n in ((self.proc.stdout, "stdout"), (self.proc.stderr, "stderr"))]
            for p in pumps:
                p.start()
            timeout = self.a.timeout or self.f.run["timeout_s"]
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                self.stop("timeout")
                self.proc.wait()
            self.exit_after_stop = round(time.monotonic() - self.stop_at, 2) if self.stop_at else None
            for p in pumps:
                p.join(5)
            code = self.proc.returncode
        finally:
            self.teardown()
        return self.result(code, before, tools, time.time() - t0)

    def teardown(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.kill()
            self.proc.wait(10)
        if self.docker:
            docker("rm", "-f", f"hi-run-{self.sid}")
        if self.net:
            self.net.__exit__()
        if self.gw:
            self.gw.close()
        if self.secret:
            self.secret.teardown()

    def result(self, code: int, before: dict, tools: Path, seconds: float) -> dict:
        try:
            out = json.loads((self.rundir / "output.json").read_text())
        except (OSError, json.JSONDecodeError):
            out = {}
        status = out.get("status")
        if status not in ("ok", "fail", "stopped"):        # missing, or still "running": the run was cut off
            status = "stopped" if self.stop_reason and out.get("resume") else "fail"
        after = snapshot(self.ws)
        res = {"session": self.sid, "harness": self.f.name, "mode": "local" if self.a.local else "docker",
               "status": status, "answer": out.get("answer", ""), "resume": out.get("resume"),
               "usage": out.get("usage", {}), "cost_usd": out.get("cost_usd"), "steers": out.get("steers", 0),
               "steers_sent": self.steers_sent, "stop": self.stop_reason,
               "stop_to_exit_s": getattr(self, "exit_after_stop", None), "exit_code": code,
               "seconds": round(seconds, 2), "stdout_lines": self.lines,
               "files_changed": {"added": sorted(set(after) - set(before)), "deleted": sorted(set(before) - set(after)),
                                 "modified": sorted(k for k in set(before) & set(after) if before[k] != after[k])},
               "workspace": str(self.ws), "tools": str(tools), "logs": str(self.rundir)}
        if self.net:
            res["door_log"] = self.net.door_log[1:]
        (self.rundir / "result.json").write_text(json.dumps(res, indent=2))
        return res


# --- commands ------------------------------------------------------------------------------------
def clean() -> None:
    ids = docker("ps", "-aq", "--filter", "name=^hi-run-", "--filter", "name=^hi-door-",
                 "--filter", "name=^hi-install-").stdout.split()
    if ids:
        docker("rm", "-f", *(i.decode() for i in ids))
    nets = docker("network", "ls", "-q", "--filter", "name=^hi-net-").stdout.split()
    if nets:
        docker("network", "rm", *(n.decode() for n in nets))
    for d in Path("/dev/shm").glob("hi-*"):
        shutil.rmtree(d, ignore_errors=True)
    print(json.dumps({"containers": len(ids), "networks": len(nets)}))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="hirun.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("base")
    sub.add_parser("clean")
    c = sub.add_parser("check")
    c.add_argument("folder")
    i = sub.add_parser("install")
    i.add_argument("folder")
    i.add_argument("--local", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("folder")
    r.add_argument("--task", required=True)
    r.add_argument("--instructions", default="")
    r.add_argument("--model", default="")
    r.add_argument("--resume")
    r.add_argument("--workspace")
    r.add_argument("--provider-url")
    r.add_argument("--provider-api", choices=APIS)
    r.add_argument("--key-file", help="host file holding the provider key; no key = no provider")
    r.add_argument("--secret", choices=("gateway", "file", "env"), default="gateway")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--local", action="store_true")
    g.add_argument("--docker", action="store_true", help="the default")
    r.add_argument("--timeout", type=float)
    r.add_argument("--steer-after-lines", nargs=2, action="append", metavar=("N", "TEXT"))
    r.add_argument("--stop-after-lines", type=int)
    r.add_argument("--kill-after-lines", type=int, help="hard kill, no SIGINT (proves early HI_OUTPUT)")
    r.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "base":
        print(json.dumps({"tag": Base().tag, "id": Base().image_id()}))
    elif a.cmd == "clean":
        clean()
    elif a.cmd == "check":
        f = Folder(a.folder)
        ok = f.check_adapter()
        print(json.dumps({"harness": f.name, "valid": True, "hi_adapter_identical": ok}))
        sys.exit(0 if ok else 1)
    elif a.cmd == "install":
        f = Folder(a.folder)
        d, hit = Tools(f, a.local).ensure()
        print(json.dumps({"harness": f.name, "tools": str(d), "cache": "hit" if hit else "miss"}))
    else:
        f = Folder(a.folder)
        if a.steer_after_lines and f.run["interrupt"] != "steered":
            die(f"{f.name} is run.interrupt={f.run['interrupt']}: stop it and run again with --resume instead")
        if not f.check_adapter():
            die(f"{f.path}/hi_adapter.py differs from {CANON_ADAPTER}")
        print(json.dumps(Run(f, a).execute(), indent=2))


if __name__ == "__main__":
    main()
