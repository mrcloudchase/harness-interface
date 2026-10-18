#!/usr/bin/env bash
# Gajae-Code, headless: -p one prompt, --mode json one event per line. A follow-up resumes the
# session id gjc printed on the first turn.
# Set in harness.json:
#   HOME: sessions land under $HOME/.gjc/agent/sessions, so -r resumes later
#   GJC_NO_TMUX: never wrap the run in a tmux session
#   GJC_NOTIFY: no desktop notifications from a headless run
#   files AGENTS.md: the request's instructions, which gjc reads from its working directory
set -euo pipefail
base="${HI_PROVIDER_URL%/}"
export ANTHROPIC_BASE_URL="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
# gjc fuzzy-matches --model; without one it may pick a non-Anthropic default, so the harness names one.
gjc -p --mode json --model "${HI_MODEL:-claude-sonnet-5-5}" \
  ${HI_SESSION_ID:+-r "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
