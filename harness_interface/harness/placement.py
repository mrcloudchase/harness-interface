"""Layer 3: where a harness installs and responds. In Docker, every install and response gets a fresh
hardened container behind its own door (`runtimes.docker`); on this machine, a plain process with no
isolation (`runtimes.local`), for developing a harness. The rest of the harness layer asks a
Placement for a runtime and never knows which it got.

A session keeps its provider's URL and key path for its whole life, since a CLI may save them with its
own session: under Docker every run has the same ones; on this machine a session keeps one runtime,
and with it one gateway port, its provider's key refreshed on every response.

Every runtime it gives carries its `owner`, the id of the data directory it serves (`owner_of`), and
its recovery sweeps that owner's leftovers alone, so servers and libraries side by side never remove
each other's runs. With no owner it has one of its own, shared with no other."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from ..runtimes.docker import DockerRuntime, Images, Provider, checked, new_owner, sweep
from ..runtimes.local import LocalRuntime
from ..runtimes.process import host_env

SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"   # the base image's


@dataclass(frozen=True)
class Placement:
    images: Images | None = None                     # Docker, building its images with these; None: this machine
    ca_file: Path | None = None                      # the CA bundle for TLS, where the network re-signs it
    owner: str = field(default_factory=new_owner)    # whose runs these are: `owner_of(data directory)`
    _local: dict[str, LocalRuntime] = field(default_factory=dict, compare=False, repr=False)   # by session

    def __post_init__(self) -> None:
        checked(self.owner)

    @property
    def docker(self) -> bool:
        return self.images is not None

    @property
    def path(self) -> str:
        """What follows the tools' bin directory on a run's PATH."""
        return SYSTEM_PATH if self.docker else host_env().get("PATH", SYSTEM_PATH)

    def runtime(self, image: str | None, *, read_only: Sequence[Path] = (), writable: Sequence[Path] = (),
                egress: Sequence[str] = (), provider: Provider | None = None,
                session: str | None = None) -> DockerRuntime | LocalRuntime:
        """A runtime for one install or response: in Docker, in `image`, with these mounts and hosts; on
        this machine, the session's own, one response at a time."""
        if self.docker:
            return DockerRuntime(image, read_only=read_only, writable=writable, egress=egress, provider=provider,
                                 ca_file=self.ca_file, owner=self.owner)
        mode = provider and provider.credential
        runtime = self._local.get(session) if session else None
        if runtime is None or (runtime.provider and runtime.provider.credential) != mode:
            runtime = LocalRuntime(provider, ca_file=self.ca_file, owner=self.owner)
            if session:
                self._local[session] = runtime
        runtime.provider = provider                  # its key may have been replaced; its URL and path stay
        return runtime

    async def recover(self) -> None:
        """Remove whatever this owner's installs and responses a crash cut off left behind."""
        if self.docker:
            await sweep(self.owner)
