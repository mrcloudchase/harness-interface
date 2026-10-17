#!/usr/bin/env bash
# OpenHands CLI, headless: --headless --json streams one event per line, --override-with-envs reads
# LLM_MODEL / LLM_API_KEY / LLM_BASE_URL instead of the saved settings, --always-approve skips
# confirmations. Its stdout mixes Rich status lines with the JSON events; the reporter keeps both.
set -euo pipefail
model="${HI_MODEL:-claude-sonnet-4-5}"
[[ "$model" == */* ]] || model="anthropic/$model"   # litellm wants the provider prefix
export LLM_MODEL="$model" LLM_API_KEY="$HI_PROVIDER_KEY" LLM_BASE_URL="${HI_PROVIDER_URL%/}"
openhands --headless --json --override-with-envs --always-approve --exit-without-confirmation \
  ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} -t "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
