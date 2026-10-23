#!/usr/bin/env bash
set -euo pipefail
VERSION=0.25.2
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "@qwen-code/qwen-code@$VERSION"
"$HG_TOOLS/bin/qwen" --version
