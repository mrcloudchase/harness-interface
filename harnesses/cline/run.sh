#!/usr/bin/env bash
# Cline CLI, headless, through its ACP mode: `cline -p` cannot resume (`--id` always opens the
# interactive UI), but ACP can load a saved session. `cline auth` saves the key as the anthropic
# provider's, under $HOME/.cline (inside .home/, never listed); CLINE_PROVIDER and CLINE_MODEL pick
# it for ACP sessions, and ACP starts a session only once CLINE_API_KEY is set. HI_PROVIDER_URL is
# ignored: the anthropic provider has no base URL setting.
# Set in harness.json:
#   HOME: the provider settings and the sessions live under $HOME/.cline, so a follow-up loads the session
#   files AGENTS.md: the request's instructions, which cline reads from its working directory
set -euo pipefail
export CLINE_PROVIDER=anthropic CLINE_MODEL="${HI_MODEL:-claude-sonnet-4-5}" CLINE_API_KEY="$HI_PROVIDER_KEY"
cline auth anthropic -k "$HI_PROVIDER_KEY" -m "$CLINE_MODEL" >&2
python3 "$HI_HARNESS_DIR/acp.py" </dev/null | python3 "$HI_HARNESS_DIR/report.py"
