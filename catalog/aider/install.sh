#!/usr/bin/env bash
set -euo pipefail
VERSION=0.86.2
python3 -m venv "$HI_TOOLS/aider-venv"
"$HI_TOOLS/aider-venv/bin/pip" install -q --disable-pip-version-check "aider-chat==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../aider-venv/bin/aider "$HI_TOOLS/bin/aider"
"$HI_TOOLS/bin/aider" --version
