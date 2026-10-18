"""Where things live and how runs are executed. Everything from the environment, with a default."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Settings(BaseModel):
    host: str = os.environ.get("HI_HOST", "127.0.0.1")
    port: int = int(os.environ.get("HI_PORT", "8000"))
    data_dir: Path = Path(os.environ.get("HI_DATA_DIR", "data")).resolve()
    runtime: Literal["docker", "local"] = os.environ.get("HI_RUNTIME", "docker")  # type: ignore[assignment]

    @property
    def workspaces(self) -> Path: return self.data_dir / "workspaces"
    @property
    def responses(self) -> Path: return self.data_dir / "responses"
    @property
    def logs(self) -> Path: return self.data_dir / "logs"

    def out_path(self, response_id: str) -> Path:
        """The harness's stdout, as it printed it."""
        return self.logs / f"{response_id}.out"

    def log_path(self, response_id: str) -> Path:
        """The harness's stderr."""
        return self.logs / f"{response_id}.log"
