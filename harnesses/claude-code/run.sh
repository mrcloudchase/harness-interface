#!/usr/bin/env bash
# Claude Code, headless. Everything specific to this CLI lives in this folder.
# The server gives HI_TASK, HI_MODEL, HI_SESSION_ID, HI_OUTPUT, HI_HARNESS_DIR, HI_PROVIDER_URL, HI_PROVIDER_KEY.
# Set in harness.json:
#   HOME: transcripts land inside the workspace, so --resume works later
#   IS_SANDBOX: claude refuses --dangerously-skip-permissions as root without this
#   files AGENTS.md: the request's instructions, which claude reads from its working directory
set -euo pipefail
# The CLI appends /v1/messages itself, so the provider URL must not end in /v1.
base="${HI_PROVIDER_URL%/}"
export ANTHROPIC_BASE_URL="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY" ANTHROPIC_AUTH_TOKEN="$HI_PROVIDER_KEY"
claude -p "$HI_TASK" --output-format stream-json --verbose --dangerously-skip-permissions \
  ${HI_MODEL:+--model "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} \
  | python3 "$HI_HARNESS_DIR/report.py"
