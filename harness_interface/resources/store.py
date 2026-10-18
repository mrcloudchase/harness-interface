"""Layer 4: one JSON file per record. Every store shares this; another kind of storage is another
class with the same four methods."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


class JsonStore(Generic[T]):
    def __init__(self, root: Path, load: Callable[[dict[str, Any]], T], private: bool = False):
        self.root, self.load, self.mode = root, load, 0o600 if private else 0o644
        root.mkdir(parents=True, exist_ok=True)
        if private:
            os.chmod(root, 0o700)

    def _path(self, key: str) -> Path:
        assert key and "/" not in key and not key.startswith("."), key
        return self.root / f"{key}.json"

    def put(self, key: str, item: T) -> T:
        """Written whole or not at all: a reader never sees half a record."""
        p = self._path(key)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(json.dumps(asdict(item), indent=2))
        tmp.chmod(self.mode)
        os.replace(tmp, p)
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
