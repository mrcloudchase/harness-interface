#!/usr/bin/env bash
set -euo pipefail
VERSION=0.25.2
mkdir -p "$HG_TOOLS/bin" "$HG_TOOLS/lib"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund --strict-allow-scripts --allow-scripts=@qwen-code/audio-capture "@qwen-code/qwen-code@$VERSION"
"$HG_TOOLS/bin/qwen" --version
