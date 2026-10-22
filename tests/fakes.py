"""Stand-ins: a test package as a tar, and a runtime that runs the turn as a process on this machine."""
from __future__ import annotations

import io
import json
import os
import tarfile
from pathlib import Path

from harness_interface.execution import Execution, Spec
from harness_interface.runtimes.process import ProcessExecution, host_env

HARNESS_JSON = {"contract": 4, "description": "a test harness",
                "defaults": {"provider": "prov", "model": "m1"},
                "provider_env": {"key": "FAKE_KEY", "url": "FAKE_URL"}, "interrupt": "SIGUSR1",
                "install": {"egress": ["registry.example"], "timeout_s": 60},
                "run": {"egress": ["git.example"], "timeout_s": 60, "stop_timeout_s": 2}}
REQUEST_SH = """#!/usr/bin/env bash
set -eu
prompt=$(cat)
echo "prompt=$prompt turn=$HI_TURN model=$HI_MODEL key=${FAKE_KEY:-} url=${FAKE_URL:-} ins=${HI_INSTRUCTIONS:-}"
echo "stderr line" >&2
echo "$prompt" > out.txt
[ -f "$HOME/org.txt" ] && echo "org=$(cat "$HOME/org.txt")"
[ -f "$HOME/user.txt" ] && echo "user=$(cat "$HOME/user.txt")"
[ -f README.md ] && echo "project=$(cat README.md)"
[ -f "$HI_REQUEST" ] && echo "request=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['input'])" "$HI_REQUEST")"
exit 0
"""
RESPONSE_SH = """#!/usr/bin/env bash
echo "shaped: outcome=$HI_OUTCOME exit=$HI_EXIT $(head -1 "$HI_STDOUT")"
"""
INSTALL_SH = "#!/usr/bin/env bash\nset -eu\nmkdir -p \"$HI_TOOLS/bin\"\nprintf '#!/bin/sh\\necho tool-ran\\n' > \"$HI_TOOLS/bin/tool\"\nchmod +x \"$HI_TOOLS/bin/tool\"\n"


def archive(files: dict[str, str | bytes | None] | None = None, root: str = "", **changes: str) -> bytes:
    """A package as a tar: the test package, with `files` replacing or adding members (None removes)
    and `changes` replacing harness.json's top-level keys (JSON text for objects). `root` wraps it."""
    config = {**HARNESS_JSON, **{k: json.loads(v) if v.startswith(("{", "[")) else v for k, v in changes.items()}}
    members: dict[str, str | bytes | None] = {"harness.json": json.dumps(config), "install.sh": INSTALL_SH,
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
    """Runs a spec as a process here, with the spec's environment plus the host's PATH; the token
    file and provider URL a Docker runtime would give are faked."""

    def __init__(self, token: str = ""):
        self.token = token
        self.provider_url = "http://hi-provider:8080" if token else None
        self.token_path: Path | None = None

    async def start(self, spec: Spec) -> Execution:
        env = {**spec.env, "PATH": f"{spec.env.get('PATH', '')}:{host_env().get('PATH', os.defpath)}"}
        return await ProcessExecution.spawn(list(spec.command), env=env, cwd=spec.workspace, input=spec.input,
                                            interactive=spec.interactive, timeout_s=spec.timeout_s)

    async def recover(self) -> None:
        pass
