#!/usr/bin/env bash
# DeepSeek Harness, headless. `--json` emits NDJSON run events; `--session-id` resumes a session
# persisted under $HOME/.dsh. The model is chosen by the profile, not a flag, so HI_MODEL is unused.
set -euo pipefail
dsh --profile headless --json ${HI_SESSION_ID:+--session-id "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
