#!/usr/bin/env bash
# OpenCode, headless: `run --format json` emits one event per line, `--auto` approves tool calls,
# `-s <id>` continues a session stored under $HOME. Models are named provider/model.
# Set in harness.json:
#   HOME: sessions live in $HOME/.local/share/opencode/opencode.db, so --session resumes later
set -euo pipefail
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
# The anthropic provider appends /messages itself, so the base URL must end in /v1.
base="${HI_PROVIDER_URL%/}"
export OPENCODE_CONFIG_CONTENT="{\"provider\":{\"anthropic\":{\"options\":{\"baseURL\":\"${base%/v1}/v1\"}}}}"
model="${HI_MODEL:-claude-sonnet-4-5}"; [[ "$model" == */* ]] || model="anthropic/$model"
opencode run --format json --auto -m "$model" ${HI_SESSION_ID:+-s "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
