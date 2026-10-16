"""Where things live and how to reach Jev. Everything comes from the environment with a default."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    data_dir: Path = Path(os.environ.get("HI_DATA_DIR", "data")).resolve()
    jev_base_url: str = os.environ.get("JEV_BASE_URL", "https://api.typesafe.ai/v1")
    jev_secret_name: str = os.environ.get("JEV_SECRET_NAME", "TYPESAFE_API_KEY")
    check_timeout_s: int = int(os.environ.get("HI_CHECK_TIMEOUT_S", "60"))

    @property
    def workspaces(self) -> Path: return self.data_dir / "workspaces"
    @property
    def runs(self) -> Path: return self.data_dir / "runs"
    @property
    def sessions(self) -> Path: return self.data_dir / "sessions"
    @property
    def harnesses(self) -> Path: return self.data_dir / "harnesses"
    @property
    def routes(self) -> Path: return self.data_dir / "routes"
    @property
    def secrets(self) -> Path: return self.data_dir / "secrets"
    @property
    def logs(self) -> Path: return self.data_dir / "logs"
