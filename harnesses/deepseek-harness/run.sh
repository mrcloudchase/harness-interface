#!/usr/bin/env bash
# DeepSeek Harness, headless. `--json` emits NDJSON run events; `--session-id` resumes a session
# persisted under $HOME/.dsh.
set -euo pipefail
export DEEPSEEK_BASE_URL="${HI_PROVIDER_URL%/}" DEEPSEEK_API_KEY="$HI_PROVIDER_KEY"
[ -n "${HI_MODEL:-}" ] && export DEEPSEEK_DEFAULT_MODEL="$HI_MODEL"
dsh --profile headless --json ${HI_SESSION_ID:+--session-id "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
