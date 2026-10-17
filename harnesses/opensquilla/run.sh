#!/usr/bin/env bash
# OpenSquilla, headless: `opensquilla agent --json` runs one turn and prints one JSON object.
# The harness picks the session id itself; a follow-up replays it from the session database.
set -euo pipefail
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
mkdir -p "$HOME/.opensquilla"
cat > "$HOME/.opensquilla/config.toml" <<CFG
config_version = 2

[llm]
provider = "anthropic"
model = "${HI_MODEL:-claude-sonnet-5-5}"
api_key_env = "ANTHROPIC_API_KEY"
base_url = "${HI_PROVIDER_URL%/}"

[squilla_router]
enabled = false
CFG
opensquilla agent --json --permissions bypass --workspace "$HI_WORKSPACE" \
  --session-id "${HI_SESSION_ID:-$(date +%s)-$$}" --session-db-path "$HOME/.opensquilla/sessions.db" \
  -m "$HI_TASK" | python3 "$HI_HARNESS_DIR/report.py"
