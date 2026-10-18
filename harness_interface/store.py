"""One JSON file per record. Four stores share this; swap the module for a database later."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class JsonStore(Generic[T]):
    def __init__(self, root: Path, model: type[T], private: bool = False):
        self.root, self.model, self.mode = root, model, 0o600 if private else 0o644
        root.mkdir(parents=True, exist_ok=True)
        if private:
            os.chmod(root, 0o700)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def put(self, key: str, obj: T) -> T:
        """Written whole or not at all: a reader never sees half a record."""
        p = self._path(key)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(obj.model_dump_json(indent=2))
        tmp.chmod(self.mode)
        os.replace(tmp, p)
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
