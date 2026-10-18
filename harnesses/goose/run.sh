#!/usr/bin/env bash
# Goose, headless: `run -t` one prompt, `--output-format stream-json` one event per line. Quiet mode
# would hide the only place the session id is printed (the startup banner), so it stays off.
# A follow-up resumes with `-r --session-id`.
# Set in harness.json:
#   HOME: sessions live in $HOME/.local/share/goose/sessions/sessions.db, so --resume works later
#   GOOSE_MODE: approve tool calls without asking
#   files AGENTS.md: the request's instructions, which goose reads from its working directory
set -euo pipefail
base="${HI_PROVIDER_URL%/}"
export ANTHROPIC_HOST="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
export GOOSE_PROVIDER=anthropic GOOSE_MODEL="${HI_MODEL:-claude-sonnet-4-5}"
goose run --output-format stream-json ${HI_SESSION_ID:+-r --session-id "$HI_SESSION_ID"} -t "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
