#!/usr/bin/env bash
set -euo pipefail
VERSION=0.1.15
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@mimo-ai/cli@$VERSION"
HOME=$(mktemp -d) "$HI_TOOLS/bin/mimo" --version
