#!/usr/bin/env bash
# MiMo Code, headless: `mimo run --format json` prints one event per line. A follow-up continues
# the session id from the first turn with -s. The config is passed inline, so no file is written.
set -euo pipefail
base="${HI_PROVIDER_URL%/}"; base="${base%/v1}/v1"   # mimo appends /messages, so the base carries /v1
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
export MIMOCODE_CONFIG_CONTENT="{\"provider\":{\"anthropic\":{\"options\":{\"baseURL\":\"${base}\"}}}}"
# Without --model mimo falls back to the last used or its own first model, so the harness names one.
mimo run --format json --dangerously-skip-permissions -m "anthropic/${HI_MODEL:-claude-sonnet-5-5}" \
  ${HI_SESSION_ID:+-s "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
