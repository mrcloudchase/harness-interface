#!/usr/bin/env bash
set -euo pipefail
VERSION=0.2.0-rc.2
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "@deepseek-ai/dsh@$VERSION"
"$HG_TOOLS/bin/dsh" --version </dev/null
