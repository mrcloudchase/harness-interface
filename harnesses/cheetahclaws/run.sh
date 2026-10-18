#!/usr/bin/env bash
# CheetahClaws. Its -p mode cannot resume, so the REPL is fed on stdin instead: an optional
# "/resume <id>", the task, then "/exit", which saves the session and prints its id.
# The custom provider is the only one with a configurable base URL; the model is "custom/<name>".
# Set in harness.json:
#   HOME: sessions land under $HOME/.cheetahclaws/sessions, so /resume works later
#   CHEETAH_PT_INPUT: plain readline input, no prompt_toolkit
#   files CLAUDE.md: the request's instructions, under the only name cheetahclaws reads
set -euo pipefail
mkdir -p "$HOME"   # cheetahclaws creates ~/.cheetahclaws but not its parent
export CUSTOM_BASE_URL="${HI_PROVIDER_URL%/}" CUSTOM_API_KEY="$HI_PROVIDER_KEY"
{ [ -n "${HI_SESSION_ID:-}" ] && printf '/resume %s\n' "$HI_SESSION_ID"; printf '%s\n/exit\n' "$HI_TASK"; } \
  | cheetahclaws --accept-all -m "custom/${HI_MODEL:-gpt-4.1-mini}" \
  | python3 "$HI_HARNESS_DIR/report.py"
