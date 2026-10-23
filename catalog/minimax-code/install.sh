#!/usr/bin/env bash
set -euo pipefail
VERSION=0.5.4
tmp=$(mktemp -d)
curl -fsSL "https://github.com/MiniMax-AI/minimax-code/releases/download/v$VERSION/minimax-code-$VERSION.tar.gz" -o "$tmp/mcode.tgz"
mkdir -p "$HG_TOOLS/bin" "$HG_TOOLS/lib"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund --strict-allow-scripts --allow-scripts=better-sqlite3,protobufjs --include=optional "$tmp/mcode.tgz"
"$HG_TOOLS/bin/mcode" --version
