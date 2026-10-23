#!/usr/bin/env bash
set -euo pipefail
VERSION=3.0.73
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "cline@$VERSION"
"$HG_TOOLS/bin/cline" --version
