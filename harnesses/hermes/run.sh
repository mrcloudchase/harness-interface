#!/usr/bin/env bash
# Hermes Agent, headless: -q one query, -Q quiet (final answer only), --yolo no approvals.
# It prints the answer on stdout and "session_id: ..." on stderr, so both go through the reporter.
# Set in harness.json:
#   HERMES_HOME: config, auth and the session database, so --resume works later
#   HOME: the CLI's home, inside the workspace's .home
#   files AGENTS.md: the request's instructions, which hermes reads from its working directory
set -euo pipefail
base="${HI_PROVIDER_URL%/}"
export ANTHROPIC_BASE_URL="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
hermes chat -q "$HI_TASK" -Q --yolo --accept-hooks --provider anthropic \
  ${HI_MODEL:+-m "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} 2>&1 \
  | python3 "$HI_HARNESS_DIR/report.py"
