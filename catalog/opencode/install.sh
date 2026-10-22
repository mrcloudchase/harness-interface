#!/usr/bin/env bash
set -euo pipefail
VERSION=1.19.3
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "opencode-ai@$VERSION"
rm -rf "$HI_TOOLS/lib/node_modules/opencode-ai/node_modules"
"$HI_TOOLS/bin/opencode" --version
