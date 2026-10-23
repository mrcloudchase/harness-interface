#!/usr/bin/env bash
set -euo pipefail
VERSION=0.163.0
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "@openai/codex@$VERSION"
"$HG_TOOLS/bin/codex" --version
