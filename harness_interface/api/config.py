"""Layer 7: the server's settings, from the environment, each with a default. Read when the server
starts, not when this module is imported."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path | None = None                     # ~/.harness-interface/data
    runtime: str = "docker"                          # or "local"

    def __post_init__(self) -> None:
        if self.runtime not in ("docker", "local"):
            raise ValueError(f"HI_RUNTIME must be docker or local, not {self.runtime!r}")
        data = self.data_dir or Path.home() / ".harness-interface" / "data"
        object.__setattr__(self, "data_dir", Path(data).resolve())

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(host=env.get("HI_HOST", cls.host), port=int(env.get("HI_PORT", cls.port)),
                   data_dir=env.get("HI_DATA_DIR"), runtime=env.get("HI_RUNTIME", cls.runtime))
