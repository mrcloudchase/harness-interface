#!/usr/bin/env bash
# Installs the Codex CLI, pinned, into $HI_TOOLS (no secrets, egress registry.npmjs.org only).
# npm pulls the native binary as the optional dependency @openai/codex@<ver>-linux-<arch>.
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund @openai/codex@0.163.0
test "$("$HI_TOOLS/bin/codex" --version)" = "codex-cli 0.163.0"
