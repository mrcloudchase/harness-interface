#!/usr/bin/env bash
# Hermes Agent, headless: -q one query, -Q quiet (final answer only), --yolo no approvals.
# It prints the answer on stdout and "session_id: ..." on stderr, so both go through the reporter.
set -euo pipefail
base="${HI_PROVIDER_URL%/}"
export ANTHROPIC_BASE_URL="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
hermes chat -q "$HI_TASK" -Q --yolo --accept-hooks --provider anthropic \
  ${HI_MODEL:+-m "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} 2>&1 \
  | python3 "$HI_HARNESS_DIR/report.py"
