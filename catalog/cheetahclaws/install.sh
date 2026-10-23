#!/usr/bin/env bash
set -euo pipefail
VERSION=3.5.88
python3 -m venv "$HG_TOOLS/cc-venv"
"$HG_TOOLS/cc-venv/bin/pip" install -q --disable-pip-version-check "cheetahclaws==$VERSION"
mkdir -p "$HG_TOOLS/bin" && ln -sf ../cc-venv/bin/cheetahclaws "$HG_TOOLS/bin/cheetahclaws"
"$HG_TOOLS/bin/cheetahclaws" --version || true
