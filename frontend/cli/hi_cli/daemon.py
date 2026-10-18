"""The server in the background: start it, stop it, say whether it is up. Its pid and its log live
in ~/.harness-interface, beside the server's own data."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from .api import Api, ApiError

HOME = Path.home() / ".harness-interface"
PID, LOG = HOME / "server.pid", HOME / "server.log"


def running() -> int | None:
    """The pid of the background server, if it is alive."""
    try:
        pid = int(PID.read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def _executable() -> str:
    """The server installed beside this CLI, else whichever is on PATH."""
    beside = Path(sys.executable).with_name("harness-interface")
    found = str(beside) if beside.exists() else shutil.which("harness-interface")
    if not found:
        raise RuntimeError("the harness-interface server is not installed")
    return found


def start(api: Api, timeout_s: float = 60) -> int:
    """Start the server in the background on the address the CLI talks to, and wait until it
    answers. Raises with the end of its log if it stops instead."""
    if pid := running():
        return pid
    HOME.mkdir(parents=True, exist_ok=True)
    u = urlsplit(api.url)
    env = {**os.environ, "HI_HOST": u.hostname or "127.0.0.1", "HI_PORT": str(u.port or 8000)}
    with open(LOG, "ab") as log:
        proc = subprocess.Popen([_executable()], stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                env=env, start_new_session=True)
    PID.write_text(str(proc.pid))
    end = time.time() + timeout_s
    while time.time() < end:
        if proc.poll() is not None:
            PID.unlink(missing_ok=True)
            raise RuntimeError("the server stopped:\n" + tail())
        try:
            api.get("sandboxes")
            return proc.pid
        except ApiError:
            time.sleep(0.2)
    raise RuntimeError(f"the server did not answer within {timeout_s:.0f}s:\n" + tail())


def stop(timeout_s: float = 10) -> bool:
    pid = running()
    if not pid:
        PID.unlink(missing_ok=True)
        return False
    os.kill(pid, signal.SIGTERM)
    end = time.time() + timeout_s
    while time.time() < end and running():
        time.sleep(0.1)
    if running():
        os.kill(pid, signal.SIGKILL)
    PID.unlink(missing_ok=True)
    return True


def tail(lines: int = 20) -> str:
    return "\n".join(LOG.read_text(errors="replace").splitlines()[-lines:]) if LOG.exists() else ""
