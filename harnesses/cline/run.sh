#!/usr/bin/env bash
# Cline CLI, headless: `-y` auto-approves, `--json` one event per line. The key is given with `-k`,
# which also saves it under $HOME/.cline (inside .home/, never listed). HI_PROVIDER_URL is ignored:
# the anthropic provider has no base URL setting. HI_SESSION_ID is ignored: `--id` is TTY-only.
# Set in harness.json:
#   HOME: providers.json (with the key) and sessions live under $HOME/.cline
set -euo pipefail
cline -y --json -P anthropic -k "$HI_PROVIDER_KEY" -m "${HI_MODEL:-claude-sonnet-4-5}" "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
