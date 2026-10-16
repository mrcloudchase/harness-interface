"""Persistence: one JSON file per record, one file per secret. Swap this module for a database
later; nothing above it builds queries."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class JsonStore(Generic[T]):
    def __init__(self, root: Path, model: type[T]):
        self.root, self.model = root, model
        root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def put(self, key: str, obj: T) -> T:
        self._path(key).write_text(obj.model_dump_json(indent=2))
        return obj

    def get(self, key: str) -> T | None:
        p = self._path(key)
        return self.model.model_validate_json(p.read_text()) if p.exists() else None

    def list(self) -> list[T]:
        return [self.model.model_validate_json(p.read_text()) for p in sorted(self.root.glob("*.json"))]

    def delete(self, key: str) -> bool:
        p = self._path(key)
        if not p.exists():
            return False
        p.unlink()
        return True


class SecretStore:
    """Named values, file per secret, mode 600. The server's own environment is the fallback, so a
    key exported before `hi serve` works without being stored."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)

    def put(self, name: str, value: str) -> None:
        p = self.root / name
        p.write_text(value)
        p.chmod(0o600)

    def get(self, name: str) -> str | None:
        p = self.root / name
        return p.read_text() if p.exists() else os.environ.get(name)

    def names(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_file())
