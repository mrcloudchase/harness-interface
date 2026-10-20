#!/usr/bin/env bash
# Claude Code, pinned. The npm wrapper's postinstall (offline) hard-links the native binary from the
# matching optional package (@anthropic-ai/claude-code-linux-x64, glibc) over bin/claude; npm skips
# the other platforms by os, cpu and libc, and no node is needed at run time. Egress: registry.npmjs.org.
set -euo pipefail
VERSION=2.1.305
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@$VERSION"
got=$("$HI_TOOLS/bin/claude" --version)
[[ "$got" == "$VERSION"* ]] || { echo "install.sh: expected $VERSION, got: $got" >&2; exit 1; }
