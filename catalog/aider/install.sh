#!/usr/bin/env bash
set -euo pipefail
VERSION=0.86.2
python3 -m venv "$HG_TOOLS/aider-venv"
"$HG_TOOLS/aider-venv/bin/pip" install -q --disable-pip-version-check "aider-chat==$VERSION"
mkdir -p "$HG_TOOLS/bin" && ln -sf ../aider-venv/bin/aider "$HG_TOOLS/bin/aider"
"$HG_TOOLS/bin/aider" --version
