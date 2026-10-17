#!/usr/bin/env bash
# Qoder CLI, headless: -p one prompt, --output-format stream-json one event per line,
# --dangerously-skip-permissions no approvals. QODER_PAT is the headless credential; the
# provider key must be a Qoder personal access token (qoder.com), not an LLM vendor key.
set -euo pipefail
export QODER_PAT="$HI_PROVIDER_KEY"
qodercli -p "$HI_TASK" --output-format stream-json --dangerously-skip-permissions \
  ${HI_MODEL:+--model "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} \
  | python3 "$HI_HARNESS_DIR/report.py"
