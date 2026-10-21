"""Layer 6: the server's settings, from the environment, each with a default. Read when the server
starts, not when this module is imported."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"                          # HI_HOST
    port: int = 8000                                 # HI_PORT
    data_dir: Path | None = None                     # HI_DATA_DIR: ~/.harness-interface/data
    ca_file: Path | None = None                      # HI_CA_FILE: a CA bundle, where the network re-signs TLS
    admin_key: str = ""                              # HI_ADMIN_KEY: the platform's key, which creates orgs

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir or Path.home() / ".harness-interface" / "data").absolute())
        if self.ca_file is not None:
            object.__setattr__(self, "ca_file", Path(self.ca_file).absolute())

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(host=env.get("HI_HOST", cls.host), port=int(env.get("HI_PORT", cls.port)),
                   data_dir=env.get("HI_DATA_DIR") or None, ca_file=env.get("HI_CA_FILE") or None,
                   admin_key=env.get("HI_ADMIN_KEY", ""))
