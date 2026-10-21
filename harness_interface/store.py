"""Layer 3: what the server keeps, per org, on disk. One JSON file per record, written whole or not
at all; a harness version as a folder named by its digest. Nothing here runs anything.

    <data>/
      keys/<digest>.json                      an API key's digest -> its org and id (the login index)
      orgs/<org>/org.json
      orgs/<org>/members/<name>.json
      orgs/<org>/keys/<id>.json               the key's record; its secret is shown once and never kept
      orgs/<org>/providers/<name>.json        the key sealed by the vault
      orgs/<org>/sandboxes/<name>.json
      orgs/<org>/harnesses/<name>/current     the digest of the version requests run on
      orgs/<org>/harnesses/<name>/<digest>/folder/   the uploaded folder, validated
      orgs/<org>/harnesses/<name>/<digest>/tools/    install layers, one per sandbox image
      sessions/<org>/<member>/<harness>/...   the sessions layer's (sessions.py)

A name is lowercase letters, digits, dots, dashes and underscores, at most 63, starting with a
letter or digit. The same name is one thing per kind per org: orgs never collide.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

from . import harness
from .errors import Conflict, Invalid, NotFound
from .runtimes.door import APIS
from .secrets import Vault

T = TypeVar("T")
NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}")
ROLES = ("owner", "member")
PROVIDER_APIS = (*APIS, "none")                     # "none": the org's own endpoint adds the credential
KEY_PREFIX = "hi_"


def check_name(name: Any, kind: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise Invalid(f"a {kind} name is lowercase letters, digits, dots, dashes and underscores, at most 63, "
                      f"starting with a letter or digit: {name!r}")
    return name


def digest_of(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class JsonStore(Generic[T]):
    """One JSON file per record under a directory, a dataclass or a plain dict; a write replaces the file whole."""

    def __init__(self, root: Path, load: Callable[[dict[str, Any]], T]):
        self.root, self.load = Path(root), load

    def _path(self, key: str) -> Path:
        assert NAME.fullmatch(key) or re.fullmatch(r"[0-9a-f]{16,64}", key), key
        return self.root / f"{key}.json"

    def put(self, key: str, item: T) -> T:
        self.root.mkdir(parents=True, exist_ok=True)
        p = self._path(key)
        tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:8]}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(item) if is_dataclass(item) else item, f, indent=2)
            os.replace(tmp, p)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return item

    def get(self, key: str) -> T | None:
        p = self._path(key)
        return self.load(json.loads(p.read_text())) if p.is_file() else None

    def list(self) -> list[T]:
        if not self.root.is_dir():
            return []
        return [self.load(json.loads(p.read_text())) for p in sorted(self.root.glob("*.json"))]

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if not p.is_file():
            return False
        p.unlink()
        return True


@dataclass(frozen=True)
class Org:
    name: str
    created: float
    max_runs: int = 4                                # turns at once, across its members


@dataclass(frozen=True)
class Member:
    org: str
    name: str
    role: str
    created: float

    @property
    def owner(self) -> bool:
        return self.role == "owner"


@dataclass(frozen=True)
class ApiKey:
    id: str
    org: str
    member: str
    label: str
    created: float
    revoked: bool = False


@dataclass(frozen=True)
class Provider:
    """A model endpoint: its base URL, the API shape (which decides the credential's header) and
    its key, sealed. `none` is an endpoint that needs no key from us."""
    org: str
    name: str
    url: str
    api: str
    key: str = field(repr=False)                     # sealed

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "url": self.url, "api": self.api}


@dataclass(frozen=True)
class Sandbox:
    """A place to run: an image, or a Dockerfile to build one; the hosts a run may reach besides its
    provider; and its limits. Nothing of a harness is in it."""
    org: str
    name: str
    image: str = ""
    dockerfile: str = ""
    egress: tuple[str, ...] = ()
    memory: str = "4g"
    pids: int = 512

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "image": self.image, "dockerfile": self.dockerfile, "egress": list(self.egress),
                "memory": self.memory, "pids": self.pids}


@dataclass(frozen=True)
class Harness:
    """A named harness and the version requests run on."""
    org: str
    name: str
    digest: str
    created: float

    def public(self, config: harness.Config) -> dict[str, Any]:
        return {"name": self.name, "version": self.digest, "created": self.created, **config.as_json()}


class Store:
    def __init__(self, root: Path, vault: Vault):
        self.root, self.vault = Path(root).absolute(), vault
        self.root.mkdir(parents=True, exist_ok=True)
        self._logins = JsonStore(self.root / "keys", dict)

    # orgs and members
    def _org_dir(self, org: str) -> Path:
        return self.root / "orgs" / org

    def create_org(self, name: str, max_runs: int = 4) -> Org:
        check_name(name, "org")
        if self.get_org(name):
            raise Conflict(f"org {name} exists")
        return JsonStore(self._org_dir(name), lambda d: Org(**d)).put("org", Org(name, time.time(), max_runs))

    def get_org(self, name: str) -> Org | None:
        return JsonStore(self._org_dir(name), lambda d: Org(**d)).get("org") if NAME.fullmatch(name or "") else None

    def org(self, name: str) -> Org:
        if (o := self.get_org(name)) is None:
            raise NotFound(f"no org {name}")
        return o

    def orgs(self) -> list[Org]:
        base = self.root / "orgs"
        return [o for p in sorted(base.iterdir()) if base.is_dir() and (o := self.get_org(p.name))] if base.is_dir() else []

    def _members(self, org: str) -> JsonStore[Member]:
        return JsonStore(self._org_dir(org) / "members", lambda d: Member(**d))

    def create_member(self, org: str, name: str, role: str) -> Member:
        self.org(org)
        check_name(name, "member")
        if role not in ROLES:
            raise Invalid(f"a role is one of {', '.join(ROLES)}")
        if self._members(org).get(name):
            raise Conflict(f"member {name} exists")
        return self._members(org).put(name, Member(org, name, role, time.time()))

    def member(self, org: str, name: str) -> Member:
        if (m := self._members(org).get(name)) is None:
            raise NotFound(f"no member {name}")
        return m

    def members(self, org: str) -> list[Member]:
        return self._members(org).list()

    # API keys
    def _keys(self, org: str) -> JsonStore[ApiKey]:
        return JsonStore(self._org_dir(org) / "keys", lambda d: ApiKey(**d))

    def mint_key(self, org: str, member: str, label: str = "") -> tuple[ApiKey, str]:
        """A new key for a member; the secret is returned once and only its digest is kept."""
        self.member(org, member)
        secret = KEY_PREFIX + secrets.token_urlsafe(32)
        key = ApiKey(uuid.uuid4().hex[:12], org, member, label, time.time())
        self._keys(org).put(key.id, key)
        self._logins.put(digest_of(secret), {"org": org, "id": key.id})
        return key, secret

    def keys(self, org: str) -> list[ApiKey]:
        return sorted(self._keys(org).list(), key=lambda k: k.created)

    def revoke_key(self, org: str, key_id: str) -> ApiKey:
        if (k := self._keys(org).get(key_id)) is None:
            raise NotFound(f"no key {key_id}")
        return self._keys(org).put(key_id, replace(k, revoked=True))

    def resolve_key(self, secret: str) -> Member | None:
        """The member a presented secret belongs to, if it is a live key."""
        if not secret.startswith(KEY_PREFIX):
            return None
        login = self._logins.get(digest_of(secret))
        if not login:
            return None
        key = self._keys(login["org"]).get(login["id"])
        if key is None or key.revoked:
            return None
        return self._members(key.org).get(key.member)

    # providers
    def _providers(self, org: str) -> JsonStore[Provider]:
        return JsonStore(self._org_dir(org) / "providers", lambda d: Provider(**d))

    def put_provider(self, org: str, name: str, url: str, api: str, key: str) -> Provider:
        check_name(name, "provider")
        if api not in PROVIDER_APIS:
            raise Invalid(f"a provider's api is one of {', '.join(PROVIDER_APIS)}")
        if not url.startswith("https://"):
            raise Invalid("a provider's url is https://…")
        if (api == "none") != (not key):
            raise Invalid("a provider has a key, unless its api is none")
        if any(c in key for c in "\r\n\0"):
            raise Invalid("a provider's key is one line")
        sealed = self.vault.seal(key, f"{org}/providers/{name}") if key else ""
        return self._providers(org).put(name, Provider(org, name, url.rstrip("/"), api, sealed))

    def provider(self, org: str, name: str) -> Provider:
        if (p := self._providers(org).get(name)) is None:
            raise NotFound(f"no provider {name}")
        return p

    def providers(self, org: str) -> list[Provider]:
        return self._providers(org).list()

    def delete_provider(self, org: str, name: str) -> None:
        if not self._providers(org).delete(name):
            raise NotFound(f"no provider {name}")

    def open_key(self, p: Provider) -> str:
        """The provider's key, in the clear: only ever called where a run's door is being started."""
        return self.vault.open(p.key, f"{p.org}/providers/{p.name}") if p.key else ""

    # sandboxes
    def _sandboxes(self, org: str) -> JsonStore[Sandbox]:
        return JsonStore(self._org_dir(org) / "sandboxes", lambda d: Sandbox(**{**d, "egress": tuple(d["egress"])}))

    def put_sandbox(self, org: str, name: str, *, image: str = "", dockerfile: str = "", egress: list[str] = (),
                    memory: str = "4g", pids: int = 512) -> Sandbox:
        check_name(name, "sandbox")
        if bool(image) == bool(dockerfile):
            raise Invalid("a sandbox is an image or a dockerfile, one of the two")
        if not re.fullmatch(r"[0-9]+[kmg]?", memory) or not isinstance(pids, int) or pids < 1:
            raise Invalid("memory is a Docker size like 4g; pids is a positive count")
        return self._sandboxes(org).put(name, Sandbox(org, name, image, dockerfile, tuple(egress), memory, pids))

    def sandbox(self, org: str, name: str) -> Sandbox:
        if (s := self._sandboxes(org).get(name)) is None:
            raise NotFound(f"no sandbox {name}")
        return s

    def sandboxes(self, org: str) -> list[Sandbox]:
        return self._sandboxes(org).list()

    def delete_sandbox(self, org: str, name: str) -> None:
        if not self._sandboxes(org).delete(name):
            raise NotFound(f"no sandbox {name}")

    # harnesses
    def _harness_dir(self, org: str, name: str) -> Path:
        return self._org_dir(org) / "harnesses" / name

    def put_harness(self, org: str, name: str, archive: bytes) -> Harness:
        """Validate and keep an uploaded folder as the harness's current version."""
        self.org(org)
        check_name(name, "harness")
        base = self._harness_dir(org, name)
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base, prefix=".upload-") as tmp:
            folder = Path(tmp) / "folder"
            folder.mkdir()
            harness.unpack(archive, folder)
            harness.validate(folder)
            version = base / harness.digest(folder)
            if not version.is_dir():
                version.mkdir()
                shutil.move(str(folder), version / "folder")
        (base / "current").write_text(version.name)
        return Harness(org, name, version.name, time.time())

    def harness(self, org: str, name: str, digest: str | None = None) -> Harness:
        """The harness's current version, or the one named."""
        base = self._harness_dir(org, name)
        current = base / "current"
        if not NAME.fullmatch(name or "") or not current.is_file():
            raise NotFound(f"no harness {name}")
        version = digest or current.read_text().strip()
        folder = base / version / "folder"
        if not re.fullmatch(r"[0-9a-f]{16}", version) or not folder.is_dir():
            raise NotFound(f"no version {version} of harness {name}")
        return Harness(org, name, version, folder.stat().st_mtime)

    def harnesses(self, org: str) -> list[Harness]:
        base = self._org_dir(org) / "harnesses"
        return [self.harness(org, p.name) for p in sorted(base.iterdir()) if (p / "current").is_file()] if base.is_dir() else []

    def delete_harness(self, org: str, name: str) -> None:
        self.harness(org, name)
        shutil.rmtree(self._harness_dir(org, name))

    def folder(self, h: Harness) -> Path:
        return self._harness_dir(h.org, h.name) / h.digest / "folder"

    def tools_root(self, h: Harness) -> Path:
        return self._harness_dir(h.org, h.name) / h.digest / "tools"

    def config(self, h: Harness) -> harness.Config:
        return harness.load_config((self.folder(h) / "harness.json").read_text())

    @property
    def sessions_root(self) -> Path:
        return self.root / "sessions"
