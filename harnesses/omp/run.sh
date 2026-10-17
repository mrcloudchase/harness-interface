#!/usr/bin/env bash
# omp, headless: -p one prompt, --mode json one event per line, --approval-mode yolo no prompts.
# A follow-up reopens the session id that the first turn's `session` event reported.
set -euo pipefail
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
# omp wants a provider-qualified model; the harness picks a default when none is given.
omp -p --mode json --approval-mode yolo --model "anthropic/${HI_MODEL:-claude-sonnet-4-5}" \
  ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
