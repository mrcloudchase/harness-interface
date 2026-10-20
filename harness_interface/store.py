"""Layer 4: what the server keeps, by name. `JsonStore`: one JSON file per item, written whole or not at
all, readable by its owner only when it is private. `Registry`: the providers and the harnesses.

A provider is a name, the base URL its shape's official SDK takes (`check_provider_url`), its shape and
its key; the key is kept privately and never shown. A harness is a folder, sent as a map of relative
path -> text or `{"base64": …}`, stored under `harnesses/<name>/` only once it loads as contract 1 and
names itself `name`. Storing it starts its install in the background; replacing it installs it again;
a request that needs it waits for an install still running. Its install is `installing`, `ready` or
`failed`, with its log.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Generic, Mapping, TypeVar

from .errors import Invalid, NotFound
from .harness import HarnessFolder, InstallFailed, Installed, Installer, check_provider_url
from .harness.folder import NAME, relative

T = TypeVar("T")
LOG_TAIL = 65536                                     # how much of an install's log is shown


class JsonStore(Generic[T]):
    def __init__(self, root: Path, load: Callable[[dict[str, Any]], T], private: bool = False):
        self.root, self.load, self.mode = Path(root), load, 0o600 if private else 0o644
        self.root.mkdir(parents=True, exist_ok=True)
        if private:
            os.chmod(self.root, 0o700)

    def _path(self, key: str) -> Path:
        assert key and "/" not in key and not key.startswith("."), key
        return self.root / f"{key}.json"

    def put(self, key: str, item: T) -> T:
        """Written whole or not at all: a reader never sees half an item, nor anyone else a private one."""
        p = self._path(key)
        tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:8]}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, self.mode)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(item), f, indent=2)
            os.replace(tmp, p)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return item

    def get(self, key: str) -> T | None:
        p = self._path(key)
        return self.load(json.loads(p.read_text())) if p.exists() else None

    def list(self) -> list[T]:
        return [self.load(json.loads(p.read_text())) for p in sorted(self.root.glob("*.json"))]

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if not p.exists():
            return False
        p.unlink()
        return True


def check_name(name: Any, kind: str) -> None:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise Invalid(f"a {kind}'s name is lowercase letters, digits and dashes, at most 63: {name!r}")


@dataclass(frozen=True)
class ProviderEntry:
    """A model provider, by name. Its key is never shown."""
    name: str
    url: str
    api: str
    key: str = field(repr=False)

    def __post_init__(self) -> None:
        check_name(self.name, "provider")
        check_provider_url(self.url, self.api)
        if not isinstance(self.key, str) or not self.key.strip() or any(c in self.key for c in "\r\n\0"):
            raise Invalid("a provider's key is one line of text")

    def public(self) -> dict[str, str]:
        return {"name": self.name, "url": self.url, "api": self.api}


@dataclass(frozen=True)
class InstallState:
    state: str                                       # installing | ready | failed
    log: str = ""
    error: str = ""


def folder_map(path: Path) -> dict[str, str | dict[str, str]]:
    """Every file of a folder, by relative path: its text, or `{"base64": …}` when it isn't UTF-8."""
    files: dict[str, str | dict[str, str]] = {}
    for p in sorted(Path(path).rglob("*")):
        if p.is_file() and not p.is_symlink():
            data = p.read_bytes()
            try:
                files[p.relative_to(path).as_posix()] = data.decode()
            except UnicodeDecodeError:
                files[p.relative_to(path).as_posix()] = {"base64": base64.b64encode(data).decode()}
    return files


def contents(files: Mapping[str, Any]) -> dict[str, bytes]:
    """A folder map's files as bytes, or Invalid naming what is wrong with it."""
    if not isinstance(files, Mapping) or not files:
        raise Invalid("a harness is a map of relative path to its content")
    out = {}
    for rel, content in files.items():
        if not relative(rel) or any(part in ("", ".") for part in rel.split("/")):
            raise Invalid(f"a harness's file path is relative and inside it: {rel!r}")
        if isinstance(content, str):
            out[rel] = content.encode()
        elif isinstance(content, Mapping) and set(content) == {"base64"} and isinstance(content["base64"], str):
            try:
                out[rel] = base64.b64decode(content["base64"], validate=True)
            except binascii.Error:
                raise Invalid(f"{rel}: not base64") from None
        else:
            raise Invalid(f"{rel}: a file's content is text or {{\"base64\": …}}")
    return out


class Registry:
    def __init__(self, data: Path, installer: Installer):
        self.providers_store: JsonStore[ProviderEntry] = JsonStore(data / "providers", lambda d: ProviderEntry(**d),
                                                                   private=True)
        self.root, self.installer = Path(data) / "harnesses", installer
        self.root.mkdir(parents=True, exist_ok=True)
        self._installs: dict[str, asyncio.Task[Installed]] = {}

    # providers
    def put_provider(self, entry: ProviderEntry) -> ProviderEntry:
        return self.providers_store.put(entry.name, entry)

    def provider(self, name: str) -> ProviderEntry:
        found = self.providers_store.get(name) if isinstance(name, str) and NAME.fullmatch(name) else None
        if found is None:
            raise NotFound(f"no provider {name!r}")
        return found

    def providers(self) -> list[ProviderEntry]:
        return self.providers_store.list()

    def delete_provider(self, name: str) -> None:
        self.provider(name)
        self.providers_store.delete(name)

    # harnesses
    async def put_harness(self, name: str, files: Mapping[str, Any]) -> HarnessFolder:
        """Store the folder, replacing any of that name, and start its install."""
        check_name(name, "harness")
        folder = await asyncio.to_thread(self._store, name, contents(files))
        self._start_install(folder)
        return folder

    def harness(self, name: str) -> HarnessFolder:
        path = self.root / name if isinstance(name, str) and NAME.fullmatch(name) else None
        if path is None or not (path / "harness.json").is_file():
            raise NotFound(f"no harness {name!r}")
        return HarnessFolder.load(path)

    def harnesses(self) -> list[HarnessFolder]:
        return [HarnessFolder.load(p) for p in sorted(self.root.iterdir())
                if NAME.fullmatch(p.name) and (p / "harness.json").is_file()]

    def delete_harness(self, name: str) -> None:
        folder = self.harness(name)
        if task := self._installs.pop(name, None):
            task.cancel()
        shutil.rmtree(folder.path)

    def install(self, name: str) -> InstallState:
        """Where the harness's install stands; one starts if none has since the server started."""
        task = self._installs.get(name) or self._start_install(self.harness(name))
        if not task.done():
            return InstallState("installing")
        if task.cancelled():
            return InstallState("failed", error="the install was cancelled")
        if e := task.exception():
            return InstallState("failed", read_tail(getattr(e, "log", None)), str(e))
        return InstallState("ready", read_tail(task.result().log))

    async def ready(self, name: str) -> tuple[HarnessFolder, Installed]:
        """The harness and its install, waiting for one still running. Invalid if it failed."""
        while True:
            folder = self.harness(name)
            task = self._installs.get(name) or self._start_install(folder)
            try:
                return folder, await asyncio.shield(task)
            except InstallFailed as e:
                raise Invalid(f"harness {name!r} failed to install; PUT it again to retry. {e}") from None
            except asyncio.CancelledError:
                if not task.cancelled() or self._installs.get(name) is task:
                    raise                            # our own cancel, not a replaced install

    async def close(self) -> None:
        """Cut off every install still running, and wait until each has cleaned up."""
        tasks = list(self._installs.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _start_install(self, folder: HarnessFolder) -> asyncio.Task[Installed]:
        if old := self._installs.get(folder.name):
            old.cancel()
        task = asyncio.ensure_future(self.installer.ensure(folder))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())   # kept, and shown by install()
        self._installs[folder.name] = task
        return task

    def _store(self, name: str, files: dict[str, bytes]) -> HarnessFolder:
        tag = uuid.uuid4().hex[:8]
        staging, old, final = self.root / f".new-{name}-{tag}", self.root / f".old-{name}-{tag}", self.root / name
        try:
            for rel, data in files.items():
                p = staging / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            folder = HarnessFolder.load(staging)
            if folder.name != name:
                raise Invalid(f"harness.json names {folder.name!r}, not {name!r}")
            if final.exists():
                final.rename(old)
            staging.rename(final)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            shutil.rmtree(old, ignore_errors=True)
        return HarnessFolder.load(final)


def read_tail(log: Path | None) -> str:
    if not log or not Path(log).is_file():
        return ""
    with open(log, "rb") as f:
        f.seek(max(0, f.seek(0, os.SEEK_END) - LOG_TAIL))
        return f.read().decode(errors="replace")
