"""Layer 6: the platform's settings, from the environment, each with a default. Read when a process
starts, not when this module is imported. The same variables configure every role."""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

ROLES = ("api", "gateway", "worker")


@dataclass(frozen=True)
class Settings:
    roles: tuple[str, ...] = ROLES                   # --role api,gateway,worker | all
    host: str = "127.0.0.1"                          # HI_HOST: the API's bind address
    port: int = 8000                                 # HI_PORT
    public_url: str = ""                             # HI_PUBLIC_URL: how workers and signed blob URLs reach the API
    data_dir: Path = field(default_factory=lambda: Path.home() / ".harness-interface")   # HI_DATA_DIR
    records_url: str = ""                            # HI_RECORDS: sqlite:///… (default) or postgresql://…
    blobs_url: str = ""                              # HI_BLOBS: dir:///… (default) or s3://bucket
    signup: str = "closed"                           # HI_SIGNUP: open (a sign-up page creates tenants) or closed
    deployer_key: str = ""                           # HI_DEPLOYER_KEY: overrides the stored deployer key
    join_token: str = ""                             # HI_JOIN_TOKEN: what a worker presents to join
    gateway_host: str = "0.0.0.0"                    # HI_GATEWAY_HOST / HI_GATEWAY_PORT: where the gateway listens
    gateway_port: int = 8081
    gateway_url: str = ""                            # HI_GATEWAY_URL: how a run's door reaches the gateway
    base_image: str = ""                             # HI_BASE_IMAGE: the sandbox image; empty builds the shipped one
    runtime: str = ""                                # HI_RUNTIME: a sandboxed Docker runtime, e.g. runsc
    allow_private: bool = False                      # HI_ALLOW_PRIVATE=1: egress may name private addresses (self-hosted)
    ca_file: Path | None = None                      # HI_CA_FILE: a CA bundle, where the network re-signs TLS
    worker_name: str = field(default_factory=socket.gethostname)   # HI_WORKER_NAME
    worker_slots: int = 4                            # HI_WORKER_SLOTS: turns at once on this node
    control_url: str = ""                            # HI_CONTROL_URL: the API, for a worker on another machine

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir).absolute())
        object.__setattr__(self, "public_url", (self.public_url or f"http://127.0.0.1:{self.port}").rstrip("/"))
        object.__setattr__(self, "records_url", self.records_url or f"sqlite:///{self.data_dir / 'records.db'}")
        object.__setattr__(self, "blobs_url", self.blobs_url or f"dir:///{self.data_dir / 'blobs'}")
        object.__setattr__(self, "gateway_url", (self.gateway_url or f"http://host.docker.internal:{self.gateway_port}").rstrip("/"))
        object.__setattr__(self, "control_url", (self.control_url or self.public_url).rstrip("/"))
        if self.ca_file is not None:
            object.__setattr__(self, "ca_file", Path(self.ca_file).absolute())
        if self.signup not in ("open", "closed"):
            raise ValueError("HI_SIGNUP is open or closed")
        if unknown := [r for r in self.roles if r not in ROLES]:
            raise ValueError(f"unknown roles {unknown}; roles are {', '.join(ROLES)} or all")

    @classmethod
    def from_env(cls, roles: str = "all") -> Settings:
        env = os.environ
        return cls(roles=ROLES if roles == "all" else tuple(r.strip() for r in roles.split(",") if r.strip()),
                   host=env.get("HI_HOST", cls.host), port=int(env.get("HI_PORT", cls.port)),
                   public_url=env.get("HI_PUBLIC_URL", ""), data_dir=Path(env.get("HI_DATA_DIR") or Path.home() / ".harness-interface"),
                   records_url=env.get("HI_RECORDS", ""), blobs_url=env.get("HI_BLOBS", ""), signup=env.get("HI_SIGNUP", "closed"),
                   deployer_key=env.get("HI_DEPLOYER_KEY", ""), join_token=env.get("HI_JOIN_TOKEN", ""),
                   gateway_host=env.get("HI_GATEWAY_HOST", cls.gateway_host), gateway_port=int(env.get("HI_GATEWAY_PORT", cls.gateway_port)),
                   gateway_url=env.get("HI_GATEWAY_URL", ""), base_image=env.get("HI_BASE_IMAGE", ""), runtime=env.get("HI_RUNTIME", ""),
                   allow_private=env.get("HI_ALLOW_PRIVATE", "") in ("1", "true", "yes"),
                   ca_file=Path(env["HI_CA_FILE"]) if env.get("HI_CA_FILE") else None,
                   worker_name=env.get("HI_WORKER_NAME") or socket.gethostname(), worker_slots=int(env.get("HI_WORKER_SLOTS", cls.worker_slots)),
                   control_url=env.get("HI_CONTROL_URL", ""))
