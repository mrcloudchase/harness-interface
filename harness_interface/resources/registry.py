"""Layer 4: the three resources, by name. Providers, sandboxes and harnesses are stored as JSON; a
harness's scripts are also written to disk, so a run can use them. The `default` sandbox is built
in: always there, never stored, never replaced or deleted."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import Invalid, NotFound
from ..harness import Harness, Provider
from ..runtimes import Sandbox
from .store import JsonStore

NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DEFAULT_SANDBOX = Sandbox("default", Path(__file__).with_name("default.Dockerfile").read_text())
KINDS: dict[str, type] = {"providers": Provider, "sandboxes": Sandbox, "harnesses": Harness}


@dataclass(frozen=True)
class Resolved:
    """A harness, with everything it names: what a run needs."""
    harness: Harness
    provider: Provider
    sandbox: Sandbox
    scripts: Path


class Registry:
    def __init__(self, data: Path):
        self.stores: dict[str, JsonStore] = {
            "providers": JsonStore(data / "providers", lambda d: Provider(**d), private=True),
            "sandboxes": JsonStore(data / "sandboxes", lambda d: Sandbox(**d)),
            "harnesses": JsonStore(data / "harnesses", Harness.from_dict),
        }
        self.scripts = data / "scripts"

    def put(self, kind: str, item: Any) -> Any:
        assert isinstance(item, KINDS[kind]), (kind, item)
        if not NAME.match(item.name):
            raise Invalid(f"'{item.name}': a name is lowercase letters, digits and dashes, starting with a letter or digit")
        if kind == "sandboxes" and item.name == DEFAULT_SANDBOX.name:
            raise Invalid("'default' is built in; add a sandbox under another name")
        if kind == "harnesses":
            item.write_scripts(self.scripts_of(item.name))
        return self.stores[kind].put(item.name, item)

    def get(self, kind: str, name: str) -> Any:
        if kind == "sandboxes" and name == DEFAULT_SANDBOX.name:
            return DEFAULT_SANDBOX
        item = self.stores[kind].get(name) if NAME.match(name) else None
        if item is None:
            raise NotFound(f"no {kind[:-1]} '{name}'")
        return item

    def list(self, kind: str) -> list[Any]:
        return ([DEFAULT_SANDBOX] if kind == "sandboxes" else []) + self.stores[kind].list()

    def delete(self, kind: str, name: str) -> bool:
        if kind == "sandboxes" and name == DEFAULT_SANDBOX.name:
            raise Invalid("'default' is built in and can't be deleted")
        if not NAME.match(name):
            return False
        if kind == "harnesses":
            shutil.rmtree(self.scripts_of(name), ignore_errors=True)
        return self.stores[kind].delete(name)

    def scripts_of(self, harness: str) -> Path:
        return self.scripts / harness

    def resolve(self, harness: str) -> Resolved:
        """A harness by name, with its provider and sandbox. Anything missing is a refusal that
        names what is missing."""
        try:
            h = self.get("harnesses", harness)
        except NotFound:
            raise Invalid(f"no harness '{harness}'") from None
        try:
            provider = self.get("providers", h.provider)
        except NotFound:
            raise Invalid(f"harness '{h.name}' names provider '{h.provider}', which does not exist") from None
        try:
            sandbox = self.get("sandboxes", h.sandbox)
        except NotFound:
            raise Invalid(f"harness '{h.name}' names sandbox '{h.sandbox}', which does not exist") from None
        return Resolved(h, provider, sandbox, self.scripts_of(h.name))
