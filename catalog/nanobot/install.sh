#!/usr/bin/env bash
set -euo pipefail
VERSION=0.3.5
python3 -m venv "$HG_TOOLS/nb-venv"
"$HG_TOOLS/nb-venv/bin/pip" install -q --disable-pip-version-check "nanobot-ai==$VERSION"
mkdir -p "$HG_TOOLS/bin" && ln -sf ../nb-venv/bin/nanobot "$HG_TOOLS/bin/nanobot"
"$HG_TOOLS/bin/nanobot" --version
