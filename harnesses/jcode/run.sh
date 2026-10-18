#!/usr/bin/env bash
# J-Code, headless. A resumed session keeps the model it started with: jcode refuses -m on resume.
# Set in harness.json:
#   HOME: sessions live under $HOME/.jcode, so --resume works later
set -euo pipefail
base="${HI_PROVIDER_URL%/}"   # jcode appends /messages, so the base carries /v1
export ANTHROPIC_BASE_URL="${base%/v1}/v1" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
if [ -n "${HI_SESSION_ID:-}" ]; then
  jcode run --json -p anthropic-api --resume "$HI_SESSION_ID" "$HI_TASK"
else
  jcode run --json -p anthropic-api -m "${HI_MODEL:-claude-sonnet-4-5}" "$HI_TASK"
fi | python3 "$HI_HARNESS_DIR/report.py"
