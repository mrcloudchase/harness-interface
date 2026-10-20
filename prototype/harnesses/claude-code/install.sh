#!/usr/bin/env bash
# Claude Code, pinned. The npm wrapper's postinstall (local, no network) hard-links the native
# binary from the matching optional package (@anthropic-ai/claude-code-linux-x64, glibc, ~289 MB)
# over bin/claude.exe; npm skips the other platforms by os/cpu/libc. Egress: registry.npmjs.org.
set -euo pipefail
VERSION=2.1.304
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@$VERSION"
got=$("$HI_TOOLS/bin/claude" --version)
[[ "$got" == "$VERSION"* ]] || { echo "install.sh: expected $VERSION, got: $got" >&2; exit 1; }
