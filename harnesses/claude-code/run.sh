#!/usr/bin/env bash
# Claude Code, headless. Everything specific to this harness lives in this folder.
# The server gives: HI_TASK, HI_MODEL, HI_SESSION_ID, HI_OUTPUT, HI_HARNESS_DIR (see README).
set -euo pipefail
claude -p "$HI_TASK" --output-format stream-json --verbose --dangerously-skip-permissions \
  ${HI_MODEL:+--model "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} \
  | python3 "$HI_HARNESS_DIR/report.py"
