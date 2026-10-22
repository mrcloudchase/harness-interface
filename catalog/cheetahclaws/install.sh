#!/usr/bin/env bash
set -euo pipefail
VERSION=3.5.88
python3 -m venv "$HI_TOOLS/cc-venv"
"$HI_TOOLS/cc-venv/bin/pip" install -q --disable-pip-version-check "cheetahclaws==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../cc-venv/bin/cheetahclaws "$HI_TOOLS/bin/cheetahclaws"
"$HI_TOOLS/bin/cheetahclaws" --version || true
