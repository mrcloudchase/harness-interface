#!/usr/bin/env bash
set -euo pipefail
VERSION=1.16.0
python3 -m venv "$HG_TOOLS/oh-venv"
"$HG_TOOLS/oh-venv/bin/pip" install -q --disable-pip-version-check "openhands==$VERSION"
mkdir -p "$HG_TOOLS/bin" && ln -sf ../oh-venv/bin/openhands "$HG_TOOLS/bin/openhands"
"$HG_TOOLS/bin/openhands" --version || true
