#!/usr/bin/env bash
set -euo pipefail
VERSION=0.5.6
tmp=$(mktemp -d)
whl="opensquilla-$VERSION-py3-none-any.whl"
curl -fsSL "https://github.com/TokenRhythm/opensquilla/releases/download/v$VERSION/$whl" -o "$tmp/$whl"
python3 -m venv "$HI_TOOLS/sq-venv"
"$HI_TOOLS/sq-venv/bin/pip" install -q --disable-pip-version-check "$tmp/$whl"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../sq-venv/bin/opensquilla "$HI_TOOLS/bin/opensquilla"
"$HI_TOOLS/bin/opensquilla" --help >/dev/null
