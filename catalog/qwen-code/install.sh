#!/usr/bin/env bash
set -euo pipefail
VERSION=0.25.2
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@qwen-code/qwen-code@$VERSION"
"$HI_TOOLS/bin/qwen" --version
