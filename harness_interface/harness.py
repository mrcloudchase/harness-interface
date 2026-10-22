"""Layer 2: the harness package, contract 4. The only module that knows what is in one.

A package is uploaded as a tar (gzipped or not) and holds:
- `harness.json`: what the platform needs to launch it, and nothing about the CLI's behaviour;
- `install.sh`: puts the CLI into `$HI_TOOLS`, once per package version, with egress to `install.egress`;
- `request.sh`: runs one turn: the prompt on stdin, its stdout relayed live, both streams kept;
- `response.sh` (optional): runs after request.sh, reads `$HI_STDOUT`, `$HI_STDERR`, `$HI_EXIT` and
  `$HI_OUTCOME`, and prints the response; its exit code is the status. Without it the response is
  request.sh's stdout and exit code;
- `seeds/org/`, `seeds/user/`, `seeds/project/` (optional): files copied into `$HOME` every turn,
  into `$HOME` on first use only, and into the workspace when a session starts.

Nothing else is required, and nothing else is read. A package is identified by the digest of its
files, so two uploads of the same bytes are one version. The platform copies seeds and never reads
them; it parses no script and no output.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import posixpath
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import files
from .errors import Invalid

CONTRACT = 4
REQUIRED = ("harness.json", "install.sh", "request.sh")
SCRIPTS = ("install.sh", "request.sh", "response.sh")
SEEDS = ("org", "user", "project")
SIGNALS = ("SIGINT", "SIGHUP", "SIGUSR1", "SIGUSR2")   # SIGTERM is a stop; it cannot also be a steer
MAX_FILES, MAX_BYTES = 10_000, 256 * 1024 * 1024
KEYS = {"contract", "description", "defaults", "provider_env", "interrupt", "install", "run"}


@dataclass(frozen=True)
class Config:
    """harness.json, loaded. Every field has a default; a request may override the two defaults."""
    description: str = ""
    provider: str = ""
    model: str = ""
    key_env: str = ""
    url_env: str = ""
    interrupt: str = "SIGUSR1"
    install_egress: tuple[str, ...] = ()
    install_timeout_s: float = 900
    run_egress: tuple[str, ...] = ()
    timeout_s: float = 3600
    stop_timeout_s: float = 20

    def as_json(self) -> dict[str, Any]:
        return {"contract": CONTRACT, "description": self.description,
                "defaults": {"provider": self.provider, "model": self.model},
                "provider_env": {"key": self.key_env, "url": self.url_env}, "interrupt": self.interrupt,
                "install": {"egress": list(self.install_egress), "timeout_s": self.install_timeout_s},
                "run": {"egress": list(self.run_egress), "timeout_s": self.timeout_s, "stop_timeout_s": self.stop_timeout_s}}

    @property
    def egress(self) -> tuple[str, ...]:
        return tuple(sorted({*self.install_egress, *self.run_egress}))


def _text(d: dict, key: str, default: str = "") -> str:
    v = d.get(key, default)
    if not isinstance(v, str):
        raise Invalid(f"harness.json: {key} is text")
    return v


def _seconds(d: dict, key: str, default: float) -> float:
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        raise Invalid(f"harness.json: {key} is a positive number of seconds")
    return float(v)


def _section(d: dict, key: str, allowed: tuple[str, ...]) -> dict:
    s = d.get(key, {})
    if not isinstance(s, dict) or any(k not in allowed for k in s):
        raise Invalid(f"harness.json: {key} is an object with only {', '.join(allowed)}")
    return s


def _hosts(section: dict, where: str) -> tuple[str, ...]:
    egress = section.get("egress", [])
    if not isinstance(egress, list) or not all(isinstance(h, str) and h.strip() for h in egress):
        raise Invalid(f"harness.json: {where}.egress is a list of hosts")
    return tuple(h.strip() for h in egress)


def load_config(text: str) -> Config:
    try:
        d = json.loads(text)
    except ValueError as e:
        raise Invalid(f"harness.json is not JSON: {e}") from None
    return load_config_dict(d)


def load_config_dict(d: Any) -> Config:
    if not isinstance(d, dict) or d.get("contract") != CONTRACT:
        raise Invalid(f'harness.json must be an object with "contract": {CONTRACT}')
    if unknown := sorted(set(d) - KEYS):
        raise Invalid(f"harness.json: unknown keys {', '.join(unknown)}")
    defaults = _section(d, "defaults", ("provider", "model"))
    env = _section(d, "provider_env", ("key", "url"))
    install = _section(d, "install", ("egress", "timeout_s"))
    run = _section(d, "run", ("egress", "timeout_s", "stop_timeout_s"))
    for name in (env.get("key", ""), env.get("url", "")):
        if not isinstance(name, str) or (name and not name.replace("_", "").isalnum()):
            raise Invalid("harness.json: provider_env names are environment variable names")
    interrupt = _text(d, "interrupt", "SIGUSR1")
    if interrupt not in SIGNALS:
        raise Invalid(f"harness.json: interrupt is one of {', '.join(SIGNALS)}")
    return Config(description=_text(d, "description"), provider=_text(defaults, "provider"), model=_text(defaults, "model"),
                  key_env=env.get("key", ""), url_env=env.get("url", ""), interrupt=interrupt,
                  install_egress=_hosts(install, "install"), install_timeout_s=_seconds(install, "timeout_s", 900),
                  run_egress=_hosts(run, "run"), timeout_s=_seconds(run, "timeout_s", 3600),
                  stop_timeout_s=_seconds(run, "stop_timeout_s", 20))


def unpack(archive: bytes, into: Path) -> None:
    """Extract an uploaded tar into `into`: regular files and directories only, under one root. A
    single top-level directory wrapping everything (`tar czf x.tgz my-harness/`) is stripped."""
    try:
        tar = tarfile.open(fileobj=io.BytesIO(archive), mode="r:*")
    except tarfile.TarError:
        raise Invalid("a harness is uploaded as a tar archive, gzipped or not") from None
    with tar:
        members = [m for m in tar.getmembers() if m.name not in (".", "./")]
        if len(members) > MAX_FILES or sum(m.size for m in members) > MAX_BYTES:
            raise Invalid("the harness archive is too large")
        names = [posixpath.normpath(m.name) for m in members]
        if any(n.startswith(("/", "../")) or n == ".." for n in names):
            raise Invalid("the harness archive reaches outside itself")
        tops = {n.split("/", 1)[0] for n in names}
        strip = tops.pop() + "/" if len(tops) == 1 and "harness.json" not in names else ""
        for m, n in zip(members, names):
            if strip and n == strip.rstrip("/") and m.isdir():
                continue
            rel = n[len(strip):] if n.startswith(strip) else n
            dest = into / rel
            if m.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as f, open(dest, "wb") as out:
                    out.write(f.read())
                os.chmod(dest, (m.mode & 0o755) | 0o644)
            else:
                raise Invalid(f"the harness archive holds something that is not a file or directory: {m.name}")


def validate(folder: Path) -> Config:
    """The folder is a package on contract 4, or Invalid says what is missing. Its scripts are made
    executable: an upload may have lost the bit."""
    for name in REQUIRED:
        if not (folder / name).is_file():
            raise Invalid(f"a harness package needs {', '.join(REQUIRED)}: {name} is missing")
    config = load_config((folder / "harness.json").read_text(errors="replace"))
    for name in SCRIPTS:
        script = folder / name
        if not script.is_file():
            continue
        os.chmod(script, script.stat().st_mode | 0o755)
        check = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        if check.returncode != 0:
            raise Invalid(f"{name} is not valid bash: {check.stderr.strip()[-500:]}")
    seeds = folder / "seeds"
    if seeds.exists():
        if not seeds.is_dir():
            raise Invalid("seeds is a directory")
        if unknown := sorted(p.name for p in seeds.iterdir() if p.name not in SEEDS):
            raise Invalid(f"seeds holds only {', '.join(SEEDS)}, not {', '.join(unknown)}")
    return config


def digest(folder: Path) -> str:
    """The package's identity: its files' paths and bytes."""
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            h.update(f"{p.relative_to(folder).as_posix()}\0".encode())
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()[:16]


def pack(folder: Path) -> bytes:
    """The validated folder as a gzipped tar, the canonical form kept and handed to workers."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                tar.add(p, arcname=p.relative_to(folder).as_posix())
    return buf.getvalue()


def seed(folder: Path, kind: str) -> Path | None:
    p = folder / "seeds" / kind
    return p if p.is_dir() else None


def copy_seed(source: Path, into: Path, overwrite: bool) -> None:
    """Every file under `source` into `into`, through the safe writer, so nothing the sandbox left in
    `into` can redirect a copy; an existing file is replaced only when `overwrite`."""
    for p in sorted(source.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = p.relative_to(source).as_posix()
        if not overwrite and files.exists(into, rel):
            continue
        files.write(into, rel, p.read_bytes(), (p.stat().st_mode & 0o755) | 0o644)
