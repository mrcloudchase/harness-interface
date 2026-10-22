#!/usr/bin/env bash
set -euo pipefail
VERSION=3.0.73
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "cline@$VERSION"
"$HI_TOOLS/bin/cline" --version
