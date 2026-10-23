"""Layer 3: what the platform keeps, per tenant, as records and blobs. Nothing here runs anything.

    tenant/<name>                       the tenant: created, limits, status
    member/<tenant>/<name>              owner or member
    key/<tenant>/<id>                   an API key's record; its secret is shown once, its digest kept in login/
    provider/<tenant>/<name>            a model endpoint, its API shape, its key sealed by the vault
    harness/<tenant>/<name>             the package: its current version, and every version's config
      blob tenants/<tenant>/harnesses/<name>/<digest>.tgz    the validated folder, canonical
    login/<digest>, deployer/key, worker/<id>, token/<digest>   platform-level: the empty tenant

A name is lowercase letters, digits, dots, dashes and underscores, at most 63, starting with a letter
or digit. The same name is one thing per kind per tenant; tenants never collide.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import harness
from .blobs import Blobs
from .errors import Conflict, Invalid, NotFound
from .limits import Limits
from .records import Records
from .runtimes.door import check_host
from .secrets import Vault

NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,62}")
ROLES = ("owner", "member")
APIS = ("anthropic-messages", "openai-responses", "openai-chat", "none")
KEY_PREFIX = "hg_"
PLATFORM = ""                                        # the tenant of platform-level records


def check_name(name: Any, kind: str) -> str:
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise Invalid(f"a {kind} name is lowercase letters, digits, dots, dashes and underscores, at most 63, "
                      f"starting with a letter or digit: {name!r}")
    return name


def digest_of(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def session_token(api: str) -> str:
    """A session's stand-in for its key under the gateway, shaped like a real one for CLIs that check."""
    return ("sk-ant-api03-hg-" if api == "anthropic-messages" else "sk-hg-") + secrets.token_hex(24)


@dataclass(frozen=True)
class Tenant:
    name: str
    created: float
    limits: dict[str, Any] = field(default_factory=lambda: Limits().as_dict())
    status: str = "active"                           # or suspended: its requests are refused

    @property
    def ceilings(self) -> Limits:
        return Limits.from_dict(self.limits)


@dataclass(frozen=True)
class Member:
    tenant: str
    name: str
    role: str
    created: float

    @property
    def owner(self) -> bool:
        return self.role == "owner"


@dataclass(frozen=True)
class ApiKey:
    id: str
    tenant: str
    member: str
    label: str
    created: float
    revoked: bool = False


@dataclass(frozen=True)
class Provider:
    tenant: str
    name: str
    url: str
    api: str
    key: str = field(repr=False)                     # sealed

    @property
    def path(self) -> str:
        """The URL's path, which the gateway's URL carries too, so a CLI's base-URL idioms hold."""
        from urllib.parse import urlsplit
        return urlsplit(self.url).path.rstrip("/")

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "url": self.url, "api": self.api}


@dataclass(frozen=True)
class Harness:
    tenant: str
    name: str
    current: str
    created: float
    versions: dict[str, dict[str, Any]] = field(default_factory=dict)   # digest -> {config, created}

    def config(self, digest: str | None = None) -> harness.Config:
        v = self.versions.get(digest or self.current)
        if v is None:
            raise NotFound(f"no version {digest} of harness {self.name}")
        return harness.load_config_dict(v["config"])

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.current, "created": self.created,
                "versions": sorted(self.versions, key=lambda d: self.versions[d]["created"]), **self.config().as_json()}


@dataclass(frozen=True)
class Worker:
    id: str
    name: str
    created: float
    last_seen: float
    slots: int = 0
    running: int = 0
    version: str = ""


class Store:
    def __init__(self, records: Records, blobs: Blobs, vault: Vault, allow_private: bool = False):
        self.records, self.blobs, self.vault, self.allow_private = records, blobs, vault, allow_private

    # tenants
    def create_tenant(self, name: str, limits: dict[str, Any] | None = None) -> Tenant:
        check_name(name, "tenant")
        if self.records.get("tenant", PLATFORM, name):
            raise Conflict(f"tenant {name} exists")
        t = Tenant(name, time.time(), Limits.from_dict(limits).as_dict())
        self.records.put("tenant", PLATFORM, name, asdict(t))
        return t

    def tenant(self, name: str) -> Tenant:
        d = self.records.get("tenant", PLATFORM, name) if NAME.fullmatch(name or "") else None
        if d is None:
            raise NotFound(f"no tenant {name}")
        return Tenant(**d)

    def tenants(self) -> list[Tenant]:
        return [Tenant(**d) for d in self.records.list("tenant", PLATFORM)]

    def update_tenant(self, name: str, *, limits: dict[str, Any] | None = None, status: str | None = None) -> Tenant:
        t = self.tenant(name)
        if status is not None and status not in ("active", "suspended"):
            raise Invalid("a tenant's status is active or suspended")
        t = Tenant(t.name, t.created, Limits.from_dict(limits).as_dict() if limits is not None else t.limits, status or t.status)
        self.records.put("tenant", PLATFORM, name, asdict(t))
        return t

    def delete_tenant(self, name: str) -> None:
        self.tenant(name)
        for kind in ("member", "key", "provider", "harness", "session", "response", "turn", "chunk", "usage", "trace", "rodeo", "invite"):
            for d in self.records.list(kind, name):
                self.records.delete(kind, name, d.get("id") or d.get("name") or d.get("key"))
        for login in self.records.where("login", "tenant", name, limit=10_000):
            self.records.delete("login", PLATFORM, login[1])
        self.blobs.delete(f"tenants/{name}")
        self.records.delete("tenant", PLATFORM, name)

    # members and keys
    def create_member(self, tenant: str, name: str, role: str) -> Member:
        self.tenant(tenant)
        check_name(name, "member")
        if role not in ROLES:
            raise Invalid(f"a role is one of {', '.join(ROLES)}")
        if self.records.get("member", tenant, name):
            raise Conflict(f"member {name} exists")
        m = Member(tenant, name, role, time.time())
        self.records.put("member", tenant, name, asdict(m))
        return m

    def member(self, tenant: str, name: str) -> Member:
        d = self.records.get("member", tenant, name) if NAME.fullmatch(name or "") else None
        if d is None:
            raise NotFound(f"no member {name}")
        return Member(**d)

    def members(self, tenant: str) -> list[Member]:
        return [Member(**d) for d in self.records.list("member", tenant)]

    def mint_key(self, tenant: str, member: str, label: str = "") -> tuple[ApiKey, str]:
        """A new key for a member; the secret is returned once and only its digest is kept."""
        self.member(tenant, member)
        secret = KEY_PREFIX + secrets.token_urlsafe(32)
        key = ApiKey(uuid.uuid4().hex[:12], tenant, member, label, time.time())
        self.records.put("key", tenant, key.id, asdict(key))
        self.records.put("login", PLATFORM, digest_of(secret), {"tenant": tenant, "id": key.id})
        return key, secret

    def keys(self, tenant: str) -> list[ApiKey]:
        return sorted((ApiKey(**d) for d in self.records.list("key", tenant)), key=lambda k: k.created)

    def revoke_key(self, tenant: str, key_id: str) -> ApiKey:
        d = self.records.get("key", tenant, key_id) if re.fullmatch(r"[0-9a-f]{12}", key_id or "") else None
        if d is None:
            raise NotFound(f"no key {key_id}")
        k = ApiKey(**{**d, "revoked": True})
        self.records.put("key", tenant, key_id, asdict(k))
        return k

    def resolve_key(self, secret: str) -> Member | None:
        """The member a presented secret belongs to, if it is a live key of an active tenant."""
        if not secret.startswith(KEY_PREFIX):
            return None
        login = self.records.get("login", PLATFORM, digest_of(secret))
        if not login:
            return None
        key = self.records.get("key", login["tenant"], login["id"])
        if key is None or key["revoked"]:
            return None
        try:
            if self.tenant(key["tenant"]).status != "active":
                return None
            return self.member(key["tenant"], key["member"])
        except NotFound:
            return None

    # providers
    def put_provider(self, tenant: str, name: str, url: str, api: str, key: str) -> Provider:
        self.tenant(tenant)
        check_name(name, "provider")
        if api not in APIS:
            raise Invalid(f"a provider's api is one of {', '.join(APIS)}")
        if not url.startswith("https://"):
            raise Invalid("a provider's url is https://…")
        try:
            check_host(url, self.allow_private)
        except ValueError as e:
            raise Invalid(f"a provider's url: {e}") from None
        if (api == "none") != (not key):
            raise Invalid("a provider has a key, unless its api is none")
        if any(c in key for c in "\r\n\0"):
            raise Invalid("a provider's key is one line")
        sealed = self.vault.seal(key, f"{tenant}/providers/{name}") if key else ""
        p = Provider(tenant, name, url.rstrip("/"), api, sealed)
        self.records.put("provider", tenant, name, asdict(p))
        return p

    def provider(self, tenant: str, name: str) -> Provider:
        d = self.records.get("provider", tenant, name) if NAME.fullmatch(name or "") else None
        if d is None:
            raise NotFound(f"no provider {name}")
        return Provider(**d)

    def providers(self, tenant: str) -> list[Provider]:
        return [Provider(**d) for d in self.records.list("provider", tenant)]

    def delete_provider(self, tenant: str, name: str) -> None:
        if not self.records.delete("provider", tenant, name):
            raise NotFound(f"no provider {name}")

    def open_key(self, p: Provider) -> str:
        """The provider's key, in the clear: only the gateway calls this, for one upstream request."""
        return self.vault.open(p.key, f"{p.tenant}/providers/{p.name}") if p.key else ""

    # harness packages
    @staticmethod
    def harness_blob(tenant: str, name: str, digest: str) -> str:
        return f"tenants/{tenant}/harnesses/{name}/{digest}.tgz"

    def put_harness(self, tenant: str, name: str, archive: bytes) -> Harness:
        """Validate and keep an uploaded package as the harness's current version."""
        t = self.tenant(tenant)
        check_name(name, "harness")
        if len(archive) > t.ceilings.upload_mb * 1024 * 1024:
            raise Invalid(f"the package is over the tenant's upload limit of {t.ceilings.upload_mb} MB")
        with tempfile.TemporaryDirectory(prefix="hg-upload-") as tmp:
            folder = Path(tmp) / "folder"
            folder.mkdir()
            harness.unpack(archive, folder)
            config = harness.validate(folder)
            for host in config.egress:
                try:
                    check_host(host, self.allow_private)
                except ValueError as e:
                    raise Invalid(f"harness.json egress: {e}") from None
            digest = harness.digest(folder)
            if not self.blobs.exists(self.harness_blob(tenant, name, digest)):
                self.blobs.put(self.harness_blob(tenant, name, digest), harness.pack(folder))
        existing = self.records.get("harness", tenant, name)
        versions = dict(existing["versions"]) if existing else {}
        versions.setdefault(digest, {"config": config.as_json(), "created": time.time()})
        h = Harness(tenant, name, digest, existing["created"] if existing else time.time(), versions)
        self.records.put("harness", tenant, name, asdict(h))
        return h

    def harness(self, tenant: str, name: str) -> Harness:
        d = self.records.get("harness", tenant, name) if NAME.fullmatch(name or "") else None
        if d is None:
            raise NotFound(f"no harness {name}")
        return Harness(**d)

    def harnesses(self, tenant: str) -> list[Harness]:
        return [Harness(**d) for d in self.records.list("harness", tenant)]

    def delete_harness(self, tenant: str, name: str) -> None:
        self.harness(tenant, name)
        self.blobs.delete(f"tenants/{tenant}/harnesses/{name}")
        self.records.delete("harness", tenant, name)

    # the platform's own
    def set_deployer_key(self) -> str:
        """A new deployer key, shown once; replaces the previous one."""
        secret = "hgd_" + secrets.token_urlsafe(32)
        self.records.put("deployer", PLATFORM, "key", {"digest": digest_of(secret), "created": time.time()})
        return secret

    def has_deployer_key(self) -> bool:
        return self.records.get("deployer", PLATFORM, "key") is not None

    def is_deployer(self, secret: str) -> bool:
        d = self.records.get("deployer", PLATFORM, "key")
        return bool(d) and secrets.compare_digest(d["digest"], digest_of(secret))

    def register_worker(self, name: str, slots: int, version: str) -> tuple[Worker, str]:
        secret = "hgw_" + secrets.token_urlsafe(32)
        w = Worker(uuid.uuid4().hex[:12], name, time.time(), time.time(), slots, 0, version)
        self.records.put("worker", PLATFORM, w.id, {**asdict(w), "digest": digest_of(secret)})
        return w, secret

    def worker_by_secret(self, secret: str) -> Worker | None:
        if not secret.startswith("hgw_"):
            return None
        for d in self.records.list("worker", PLATFORM):
            if secrets.compare_digest(d["digest"], digest_of(secret)):
                return Worker(**{k: v for k, v in d.items() if k != "digest"})
        return None

    def touch_worker(self, w: Worker, running: int) -> None:
        d = self.records.get("worker", PLATFORM, w.id)
        if d:
            self.records.put("worker", PLATFORM, w.id, {**d, "last_seen": time.time(), "running": running})

    def workers(self) -> list[Worker]:
        return [Worker(**{k: v for k, v in d.items() if k != "digest"}) for d in self.records.list("worker", PLATFORM)]

    def forget_worker(self, worker_id: str) -> None:
        self.records.delete("worker", PLATFORM, worker_id)

    def issue_token(self, tenant: str, provider: str, session: str, response: str, api: str, ttl_s: float) -> str:
        """A session token the gateway will swap for the provider's key, for one response."""
        secret = session_token(api)
        self.records.put("token", PLATFORM, digest_of(secret), {"tenant": tenant, "provider": provider, "session": session,
                                                                 "response": response, "expires": time.time() + ttl_s})
        return secret

    def resolve_token(self, secret: str) -> dict[str, Any] | None:
        d = self.records.get("token", PLATFORM, digest_of(secret))
        return d if d and d["expires"] > time.time() else None

    def revoke_token(self, secret: str) -> None:
        self.records.delete("token", PLATFORM, digest_of(secret))
