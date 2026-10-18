"""The three resources: stored as JSON, a harness's scripts also on disk so they can be mounted.
`default` is the built-in sandbox: always present, never stored, never deleted."""
from __future__ import annotations

import shutil
from pathlib import Path

from .errors import ClientError
from .models import Harness, Provider, Sandbox
from .store import JsonStore

DEFAULT_SANDBOX = "default"
DEFAULT_DOCKERFILE = Path(__file__).with_name("default.Dockerfile")


class Resources:
    def __init__(self, data: Path):
        self.providers = JsonStore(data / "providers", Provider, private=True)
        self.sandboxes = JsonStore(data / "sandboxes", Sandbox)
        self.harnesses = JsonStore(data / "harnesses", Harness)
        self.scripts = data / "scripts"

    # sandboxes
    def sandbox(self, name: str) -> Sandbox | None:
        if name == DEFAULT_SANDBOX:
            return Sandbox(name=DEFAULT_SANDBOX, dockerfile=DEFAULT_DOCKERFILE.read_text())
        return self.sandboxes.get(name)

    def list_sandboxes(self) -> list[Sandbox]:
        return [self.sandbox(DEFAULT_SANDBOX), *self.sandboxes.list()]

    def put_sandbox(self, spec: Sandbox) -> Sandbox:
        if spec.name == DEFAULT_SANDBOX:
            raise ClientError(f"'{DEFAULT_SANDBOX}' is built in; add a sandbox under another name")
        return self.sandboxes.put(spec.name, spec)

    def delete_sandbox(self, name: str) -> bool:
        if name == DEFAULT_SANDBOX:
            raise ClientError(f"'{DEFAULT_SANDBOX}' is built in and cannot be deleted")
        return self.sandboxes.delete(name)

    # harnesses
    def put_harness(self, spec: Harness) -> Harness:
        bad = [n for n in spec.scripts if "/" in n or n.startswith(".")]
        if bad:                                      # checked before anything on disk changes
            raise ClientError(f"script name must be a plain filename: {bad[0]!r}")
        d = self.harness_dir(spec.name)
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        for name, content in spec.scripts.items():
            (d / name).write_text(content)
        return self.harnesses.put(spec.name, spec)

    def delete_harness(self, name: str) -> bool:
        shutil.rmtree(self.harness_dir(name), ignore_errors=True)
        return self.harnesses.delete(name)

    def harness_dir(self, name: str) -> Path:
        return self.scripts / name
