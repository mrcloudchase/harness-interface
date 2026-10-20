#!/usr/bin/env bash
# The Codex CLI, pinned. npm pulls the native binary (musl, so no glibc needed) as the optional package
# @openai/codex@<version>-linux-<arch>; no node is needed at run time. Egress: registry.npmjs.org.
set -euo pipefail
VERSION=0.163.0
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@openai/codex@$VERSION"
got=$("$HI_TOOLS/bin/codex" --version)
[[ "$got" == "codex-cli $VERSION" ]] || { echo "install.sh: expected codex-cli $VERSION, got: $got" >&2; exit 1; }
