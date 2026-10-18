#!/usr/bin/env bash
# OpenSquilla, headless: `opensquilla agent --json` runs one turn and prints one JSON object.
# The harness picks the session id itself; a follow-up replays it from the session database.
# Set in harness.json:
#   HOME: config and the session database live under $HOME/.opensquilla
#   OPENSQUILLA_TRUST_ENV: honor HTTPS_PROXY
#   OPENSQUILLA_TELEMETRY_DISABLED, OPENSQUILLA_UPDATE_CHECK_DISABLED: no telemetry and no update
#     check; the sandbox reaches only the provider
#   files AGENTS.md: the request's instructions, which opensquilla reads from its working directory
set -euo pipefail
# Artifacts: each line of this folder's optional `artifacts` file names a file in the folder and
# where it goes under $HOME, as `review.md .claude/skills/review/SKILL.md`. Each is put in place
# before every turn; blank lines and lines starting with # are skipped.
if [ -f "$HI_HARNESS_DIR/artifacts" ]; then
  while read -r src dest _ || [ -n "${src:-}" ]; do
    case "$src" in ''|'#'*) continue ;; esac
    case "$src" in */*) echo "artifacts: $src is not a file in this folder" >&2; exit 2 ;; esac
    case "/$dest/" in //|*//*|*/../*|*/./*) echo "artifacts: $dest is not a path under \$HOME" >&2; exit 2 ;; esac
    mkdir -p "$(dirname "$HOME/$dest")" && cp "$HI_HARNESS_DIR/$src" "$HOME/$dest"
  done < "$HI_HARNESS_DIR/artifacts"
fi
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
