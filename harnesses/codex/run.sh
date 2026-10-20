#!/usr/bin/env bash
# Maps HI_* onto Codex's own settings, then execs the adapter. Codex reads $CODEX_HOME: config.toml,
# hooks.json and skills/ (from home/), AGENTS.md (from harness.json's files), sessions/ (resume state).
# The provider URL and key never pass through here: the adapter hands the URL to codex as a -c override
# and the key over an ephemeral app-server login, so it is in no environment, argv or file.
set -euo pipefail
cd "$HI_WORKSPACE"
export PYTHONDONTWRITEBYTECODE=1                     # nothing written into the folder or the workspace
export CODEX_HOME="$HOME/.codex"
mkdir -p "$CODEX_HOME"
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
