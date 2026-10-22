#!/usr/bin/env bash
set -euo pipefail
VERSION=1.3.0
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund --no-update-notifier "@earendil-works/pi-coding-agent@$VERSION"
PI_OFFLINE=1 "$HI_TOOLS/bin/pi" --version
