"""Layer 3: where a harness installs and responds. In Docker, every install and response gets a fresh
hardened container behind its own door (`runtimes.docker`); on this machine, a plain process with no
isolation (`runtimes.local`), for developing a harness. The rest of the harness layer asks a
Placement for a runtime and never knows which it got."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..runtimes.docker import DockerRuntime, Images, Provider
from ..runtimes.local import LocalRuntime
from ..runtimes.process import host_env

SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"   # the base image's


@dataclass(frozen=True)
class Placement:
    images: Images | None = None                     # Docker, building its images with these; None: this machine
    ca_file: Path | None = None                      # the CA bundle for TLS, where the network re-signs it

    @property
    def docker(self) -> bool:
        return self.images is not None

    @property
    def path(self) -> str:
        """What follows the tools' bin directory on a run's PATH."""
        return SYSTEM_PATH if self.docker else host_env().get("PATH", SYSTEM_PATH)

    def runtime(self, image: str | None, *, read_only: Sequence[Path] = (), writable: Sequence[Path] = (),
                egress: Sequence[str] = (), provider: Provider | None = None) -> DockerRuntime | LocalRuntime:
        """A runtime for one install or response: in Docker, in `image`, with these mounts and hosts."""
        if self.docker:
            return DockerRuntime(image, read_only=read_only, writable=writable, egress=egress, provider=provider,
                                 ca_file=self.ca_file)
        return LocalRuntime(provider, ca_file=self.ca_file)
