#!/usr/bin/env bash
set -euo pipefail
VERSION=1.16.0
python3 -m venv "$HI_TOOLS/oh-venv"
"$HI_TOOLS/oh-venv/bin/pip" install -q --disable-pip-version-check "openhands==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../oh-venv/bin/openhands "$HI_TOOLS/bin/openhands"
"$HI_TOOLS/bin/openhands" --version || true
