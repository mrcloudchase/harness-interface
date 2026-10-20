#!/usr/bin/env bash
# Maps HI_* onto hermes's own settings, then execs the adapter, which runs `hermes acp`.
# The key (or gateway token) is read by the adapter and given to hermes alone as ANTHROPIC_API_KEY.
set -euo pipefail
cd "$HI_WORKSPACE"
export HERMES_HOME="$HOME/.hermes"     # sessions (state.db), logs, caches, auth.json: all under .home
export TIRITH_ENABLED=0                # no github.com download of the tirith scanner
export HERMES_YOLO_MODE=1 HERMES_ACCEPT_HOOKS=1   # no approval prompts for commands or hooks
export HERMES_INFERENCE_PROVIDER=anthropic
unset ANTHROPIC_TOKEN CLAUDE_CODE_OAUTH_TOKEN     # these outrank ANTHROPIC_API_KEY in hermes
url="${HI_PROVIDER_URL:-https://api.anthropic.com}"; url="${url%/}"
export ANTHROPIC_BASE_URL="${url%/v1}"   # hermes adds /v1 itself; config.yaml reads it too
export PYTHONDONTWRITEBYTECODE=1        # local runs: no __pycache__ in this folder
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
