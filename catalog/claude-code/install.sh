#!/usr/bin/env bash
set -euo pipefail
VERSION=2.1.305
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@$VERSION"
"$HI_TOOLS/bin/claude" --version
