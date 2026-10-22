#!/usr/bin/env bash
set -euo pipefail
VERSION=0.19.0
mkdir -p "$HI_TOOLS/bin"
python3 -m venv "$HI_TOOLS/hermes-venv"
"$HI_TOOLS/hermes-venv/bin/pip" install -q --disable-pip-version-check "hermes-agent[anthropic]==$VERSION"
ln -sf ../hermes-venv/bin/hermes "$HI_TOOLS/bin/hermes"
"$HI_TOOLS/bin/hermes" --version
