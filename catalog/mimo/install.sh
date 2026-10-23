#!/usr/bin/env bash
set -euo pipefail
VERSION=0.1.15
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "@mimo-ai/cli@$VERSION"
HOME=$(mktemp -d) "$HG_TOOLS/bin/mimo" --version
