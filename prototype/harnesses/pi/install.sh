#!/usr/bin/env bash
# Installs pi (earendil-works/pi-coding-agent), pinned, into $HI_TOOLS. Egress: registry.npmjs.org only.
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund --no-update-notifier \
  @earendil-works/pi-coding-agent@1.3.0
PI_OFFLINE=1 "$HI_TOOLS/bin/pi" --version
