#!/usr/bin/env bash
set -euo pipefail
VERSION=0.5.4
tmp=$(mktemp -d)
curl -fsSL "https://github.com/MiniMax-AI/minimax-code/releases/download/v$VERSION/minimax-code-$VERSION.tar.gz" -o "$tmp/mcode.tgz"
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund --include=optional "$tmp/mcode.tgz"
"$HI_TOOLS/bin/mcode" --version
