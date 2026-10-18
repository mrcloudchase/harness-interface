#!/usr/bin/env bash
# omp, headless: -p one prompt, --mode json one event per line, --approval-mode yolo no prompts.
# A follow-up reopens the session id that the first turn's `session` event reported. Its stdin is
# empty: omp appends stdin to the prompt, and the server's stdin carries the request JSON.
# Set in harness.json:
#   HOME: sessions and agent.db land under $HOME/.omp/agent, so --resume works later
#   files AGENTS.md: the request's instructions, which omp reads from its working directory
set -euo pipefail
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
# omp sends model calls through PI_PROXY, not HTTPS_PROXY; in the sandbox the egress door is the only way out.
if [ -n "${HTTPS_PROXY:-}" ]; then export PI_PROXY="$HTTPS_PROXY"; fi
# omp wants a provider-qualified model; the harness picks a default when none is given.
omp -p --mode json --approval-mode yolo --model "anthropic/${HI_MODEL:-claude-sonnet-4-5}" \
  ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} "$HI_TASK" </dev/null \
  | python3 "$HI_HARNESS_DIR/report.py"
