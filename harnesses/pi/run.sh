#!/usr/bin/env bash
# pi, headless: -p one prompt, --mode json one event per line. A follow-up reopens the same
# session id, which pi creates on first use.
# Set in harness.json:
#   HOME: sessions land under $HOME/.pi/agent/sessions, so --session-id resumes later
#   files AGENTS.md: the request's instructions, which pi reads from its working directory
set -euo pipefail
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
# pi wants --model whenever --provider is given, so the harness picks a default model.
pi -p --mode json --provider anthropic --model "${HI_MODEL:-claude-sonnet-5-5}" \
  ${HI_SESSION_ID:+--session-id "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
