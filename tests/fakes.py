"""Stand-ins for the Docker layer: a runtime that runs `request.sh` as a process on this machine, and
Runtimes that hand it out. Nothing above layer 4 can tell the difference."""
from __future__ import annotations

import io
import json
import os
import tarfile
from pathlib import Path
from typing import Sequence

from harness_interface.execution import Execution, Spec
from harness_interface.runtimes.process import ProcessExecution, host_env
from harness_interface.sandboxes import path_with

HARNESS_JSON = {"contract": 3, "description": "a test harness",
                "defaults": {"sandbox": "box", "provider": "prov", "model": "m1"},
                "provider_env": {"key": "FAKE_KEY", "url": "FAKE_URL"}, "interrupt": "SIGUSR1",
                "install": {"egress": ["registry.example"], "timeout_s": 60}, "run": {"timeout_s": 60, "stop_timeout_s": 2}}
REQUEST_SH = """#!/usr/bin/env bash
set -eu
prompt=$(cat)
echo "prompt=$prompt turn=$HI_TURN model=$HI_MODEL key=${FAKE_KEY:-} url=${FAKE_URL:-} ins=${HI_INSTRUCTIONS:-}"
echo "stderr line" >&2
echo "$prompt" > out.txt
[ -f "$HOME/org.txt" ] && echo "org=$(cat "$HOME/org.txt")"
[ -f "$HOME/user.txt" ] && echo "user=$(cat "$HOME/user.txt")"
[ -f README.md ] && echo "project=$(cat README.md)"
exit 0
"""
INSTALL_SH = "#!/usr/bin/env bash\nset -eu\nmkdir -p \"$HI_TOOLS/bin\"\nprintf '#!/bin/sh\\necho tool-ran\\n' > \"$HI_TOOLS/bin/tool\"\nchmod +x \"$HI_TOOLS/bin/tool\"\n"


def archive(files: dict[str, str | bytes] | None = None, root: str = "", **changes: str) -> bytes:
    """A harness folder as a tar: the test harness, with `files` replacing or adding members and
    `changes` replacing harness.json's top-level keys. `root` wraps it in a directory."""
    config = {**HARNESS_JSON, **{k: json.loads(v) if v.startswith(("{", "[")) else v for k, v in changes.items()}}
    members: dict[str, str | bytes] = {"harness.json": json.dumps(config), "install.sh": INSTALL_SH,
                                       "request.sh": REQUEST_SH, "seeds/org/org.txt": "from-org",
                                       "seeds/user/user.txt": "from-user", "seeds/project/README.md": "from-project"}
    if files is not None:
        members = {**members, **files}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, body in members.items():
            if body is None:
                continue
            data = body.encode() if isinstance(body, str) else body
            info = tarfile.TarInfo(f"{root}/{name}" if root else name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class LocalRuntime:
    """Runs a spec as a process here, with the spec's environment plus the host's PATH."""

    def __init__(self, provider_url: str | None = None):
        self.provider_url = provider_url
        self.key_path = None

    async def start(self, spec: Spec) -> Execution:
        env = {**spec.env, "PATH": f"{spec.env.get('PATH', '')}:{host_env().get('PATH', os.defpath)}"}
        return await ProcessExecution.spawn(list(spec.command), env=env, cwd=spec.workspace, input=spec.input,
                                            interactive=spec.interactive, timeout_s=spec.timeout_s)

    async def recover(self) -> None:
        pass


class FakeRuntimes:
    """Runtimes without Docker: every image exists, tools are installed by running install.sh here."""

    def __init__(self):
        self.owner = "0" * 12
        self.installs = 0

    async def image_for(self, sandbox) -> str:
        return sandbox.image or "built:" + sandbox.name

    def runtime(self, image: str, sandbox, *, read_only: Sequence[Path] = (), writable: Sequence[Path] = (),
                provider=None, egress: Sequence[str] = ()) -> LocalRuntime:
        return LocalRuntime("http://hi-provider:8080" if provider else None)

    async def tools_for(self, folder: Path, config, root: Path, sandbox, image: str) -> Path:
        tools = root / f"{sandbox.name}-local"
        if not tools.is_dir():
            self.installs += 1
            tools.mkdir(parents=True)
            spec = Spec(("bash", str(folder / "install.sh")), env={"HI_TOOLS": str(tools), "PATH": path_with(tools)},
                        workspace=tools)
            execution = await LocalRuntime().start(spec)
            assert (await execution.wait()).ok
        return tools
