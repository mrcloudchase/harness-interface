#!/usr/bin/env bash
set -euo pipefail
VERSION=0.2.0-rc.2
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@deepseek-ai/dsh@$VERSION"
"$HI_TOOLS/bin/dsh" --version </dev/null
