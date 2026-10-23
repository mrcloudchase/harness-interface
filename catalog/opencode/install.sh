#!/usr/bin/env bash
set -euo pipefail
VERSION=1.19.3
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "opencode-ai@$VERSION"
rm -rf "$HG_TOOLS/lib/node_modules/opencode-ai/node_modules"
"$HG_TOOLS/bin/opencode" --version
