"""Layer 1: the local runtime. A process on this machine, in the spec's workspace, with the spec's
environment over the allowlisted part of this machine's.

Its guarantee is no isolation: what runs can read, write and reach anything the user running it
can. Use it for programs you trust, such as a harness you are developing.
"""
from __future__ import annotations

from ..execution import Execution, Spec
from .process import ProcessExecution, host_env


class LocalRuntime:
    async def start(self, spec: Spec) -> Execution:
        return await ProcessExecution.spawn(spec.command, env={**host_env(), **spec.env}, cwd=spec.workspace,
                                            input=spec.input, interactive=spec.interactive, timeout_s=spec.timeout_s)

    async def recover(self) -> None:
        return None                                  # a local process does not outlive what started it
