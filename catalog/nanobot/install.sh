#!/usr/bin/env bash
set -euo pipefail
VERSION=0.3.5
python3 -m venv "$HI_TOOLS/nb-venv"
"$HI_TOOLS/nb-venv/bin/pip" install -q --disable-pip-version-check "nanobot-ai==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../nb-venv/bin/nanobot "$HI_TOOLS/bin/nanobot"
"$HI_TOOLS/bin/nanobot" --version
