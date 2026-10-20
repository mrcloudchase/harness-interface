#!/usr/bin/env bash
# Codex reads $CODEX_HOME (default ~/.codex = .home/.codex): config.toml (from home/), AGENTS.md (from
# harness.json files), sessions/ (resume state). The provider URL and key are handed over by the
# adapter (a -c override and an ephemeral app-server login), never by env or auth.json.
set -euo pipefail
cd "$HI_WORKSPACE"
export CODEX_HOME="$HOME/.codex"
mkdir -p "$CODEX_HOME"
export PYTHONDONTWRITEBYTECODE=1        # no __pycache__ in the (read-only in docker) folder
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
