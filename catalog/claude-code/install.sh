#!/usr/bin/env bash
set -euo pipefail
VERSION=2.1.305
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@$VERSION"
"$HG_TOOLS/bin/claude" --version
