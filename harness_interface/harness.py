"""Layer 2: the harness folder, contract 3. The only module that knows what is in one.

A folder is uploaded as a tar (gzipped or not) and holds:
- `harness.json`: what the server needs to launch it, and nothing about the CLI's behaviour;
- `install.sh`: puts the CLI into `$HI_TOOLS`, once per sandbox, with egress to `install.egress`;
- `request.sh`: runs one turn: the prompt on stdin, its stdout and stderr the response;
- `seeds/org/`, `seeds/user/`, `seeds/project/` (optional): files copied into `$HOME` every turn,
  into `$HOME` on first use only, and into the workspace when a session starts, in the CLI's own
  formats. The server copies them and never reads them.

Nothing else is required, and nothing else is read. A folder is identified by the digest of its
files, so two uploads of the same bytes are one version.
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

from .errors import Invalid

CONTRACT = 3
REQUIRED = ("harness.json", "install.sh", "request.sh")
SCRIPTS = ("install.sh", "request.sh")
SEEDS = ("org", "user", "project")
SIGNALS = ("SIGINT", "SIGTERM", "SIGHUP", "SIGUSR1", "SIGUSR2")
MAX_FILES, MAX_BYTES = 10_000, 256 * 1024 * 1024


@dataclass(frozen=True)
class Config:
    """harness.json, loaded. Every field has a default; a request may override the three defaults."""
    description: str = ""
    sandbox: str = ""                                # defaults
    provider: str = ""
    model: str = ""
    key_env: str = ""                                # the variable names the run reads its credential and base URL from
    url_env: str = ""
    interrupt: str = "SIGUSR1"                       # the signal a steer sends, after writing $HI_DIR/interrupt
    install_egress: tuple[str, ...] = ()
    install_timeout_s: float = 900
    timeout_s: float = 3600                          # a turn's wall-clock cap
    stop_timeout_s: float = 20                       # a stop's grace before the kill

    def as_json(self) -> dict[str, Any]:
        return {"contract": CONTRACT, "description": self.description,
                "defaults": {"sandbox": self.sandbox, "provider": self.provider, "model": self.model},
                "provider_env": {"key": self.key_env, "url": self.url_env}, "interrupt": self.interrupt,
                "install": {"egress": list(self.install_egress), "timeout_s": self.install_timeout_s},
                "run": {"timeout_s": self.timeout_s, "stop_timeout_s": self.stop_timeout_s}}


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


def load_config(text: str) -> Config:
    try:
        d = json.loads(text)
    except ValueError as e:
        raise Invalid(f"harness.json is not JSON: {e}") from None
    if not isinstance(d, dict) or d.get("contract") != CONTRACT:
        raise Invalid(f'harness.json must be an object with "contract": {CONTRACT}')
    if unknown := sorted(set(d) - {"contract", "description", "defaults", "provider_env", "interrupt", "install", "run"}):
        raise Invalid(f"harness.json: unknown keys {', '.join(unknown)}")
    defaults = _section(d, "defaults", ("sandbox", "provider", "model"))
    env = _section(d, "provider_env", ("key", "url"))
    install = _section(d, "install", ("egress", "timeout_s"))
    run = _section(d, "run", ("timeout_s", "stop_timeout_s"))
    egress = install.get("egress", [])
    if not isinstance(egress, list) or not all(isinstance(h, str) and h for h in egress):
        raise Invalid("harness.json: install.egress is a list of hosts")
    for name in (env.get("key", ""), env.get("url", "")):
        if not isinstance(name, str) or (name and not name.replace("_", "").isalnum()):
            raise Invalid("harness.json: provider_env names are environment variable names")
    interrupt = _text(d, "interrupt", "SIGUSR1")
    if interrupt not in SIGNALS:
        raise Invalid(f"harness.json: interrupt is one of {', '.join(SIGNALS)}")
    return Config(description=_text(d, "description"), sandbox=_text(defaults, "sandbox"),
                  provider=_text(defaults, "provider"), model=_text(defaults, "model"),
                  key_env=env.get("key", ""), url_env=env.get("url", ""), interrupt=interrupt,
                  install_egress=tuple(egress), install_timeout_s=_seconds(install, "timeout_s", 900),
                  timeout_s=_seconds(run, "timeout_s", 3600), stop_timeout_s=_seconds(run, "stop_timeout_s", 20))


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
                continue                             # the wrapping directory itself
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
    """The folder is a harness on contract 3, or Invalid says what is missing. Its scripts are made
    executable: an upload may have lost the bit."""
    for name in REQUIRED:
        if not (folder / name).is_file():
            raise Invalid(f"a harness folder needs {', '.join(REQUIRED)}: {name} is missing")
    config = load_config((folder / "harness.json").read_text(errors="replace"))
    for name in SCRIPTS:
        script = folder / name
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
    """The folder's identity: its files' paths and bytes (modes are normalized, so they count for nothing)."""
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file():
            h.update(f"{p.relative_to(folder).as_posix()}\0".encode())
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()[:16]


def seed(folder: Path, kind: str) -> Path | None:
    """The folder's seed directory of one kind, if it has one."""
    p = folder / "seeds" / kind
    return p if p.is_dir() else None


def copy_seed(source: Path, into: Path, overwrite: bool) -> None:
    """Every file under `source` into `into`, owner-readable and -writable; an existing file is
    replaced only when `overwrite`."""
    for p in sorted(source.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        dest = into / p.relative_to(source)
        if dest.exists() and not overwrite:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(p.read_bytes())
        os.chmod(dest, (p.stat().st_mode & 0o755) | 0o644)
