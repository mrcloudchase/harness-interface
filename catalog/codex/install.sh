#!/usr/bin/env bash
set -euo pipefail
VERSION=0.163.0
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@openai/codex@$VERSION"
"$HI_TOOLS/bin/codex" --version
