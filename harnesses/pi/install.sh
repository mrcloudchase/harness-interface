#!/usr/bin/env bash
# pi (earendil-works/pi-coding-agent), pinned: JavaScript on the base image's node, nothing fetched
# but its npm packages. Egress: registry.npmjs.org.
set -euo pipefail
VERSION=1.3.0
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund --no-update-notifier \
  "@earendil-works/pi-coding-agent@$VERSION"
got=$(PI_OFFLINE=1 "$HI_TOOLS/bin/pi" --version)
[[ "$got" == "$VERSION" ]] || { echo "install.sh: expected $VERSION, got: $got" >&2; exit 1; }
