"""The template folder's stand-in harness, for tests above layer 2: the folder (or a variant of it), a
tools directory holding what its install.sh would have put there, and a way to read its events."""
import json
import shutil
from pathlib import Path

from harness_interface.harness.folder import HarnessFolder

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "harnesses" / "template"
# install.sh with nothing to fetch: the stand-in alone, so the default suite needs no network
OFFLINE_INSTALL = """#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
install -m 0755 "$HI_HARNESS_DIR/standin.py" "$HI_TOOLS/bin/standin"
"""


def variant(directory: Path, change=None, **files) -> HarnessFolder:
    """A copy of the template, its harness.json changed by `change` and `files` written (`a__b` is `a.b`)."""
    shutil.rmtree(directory, ignore_errors=True)
    shutil.copytree(TEMPLATE, directory)
    spec = json.loads((directory / "harness.json").read_text())
    if change:
        change(spec)
    (directory / "harness.json").write_text(json.dumps(spec))
    for name, content in files.items():
        (directory / name.replace("__", ".")).write_text(content)
    return HarnessFolder.load(directory)


def tools(directory: Path) -> Path:
    """A tools directory as the template's install leaves it, but for the npm helper."""
    (directory / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATE / "standin.py", directory / "bin" / "standin")
    (directory / "bin" / "standin").chmod(0o755)
    return directory


def events(stdout: bytes) -> list[dict]:
    """The NDJSON events a response printed."""
    return [json.loads(line) for line in stdout.decode().splitlines() if line.strip()]
