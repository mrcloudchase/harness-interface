#!/usr/bin/env bash
# Goose, headless: `run -t` one prompt, `--output-format stream-json` one event per line. Quiet mode
# would hide the only place the session id is printed (the startup banner), so it stays off.
# A follow-up resumes with `-r --session-id`.
# Set in harness.json:
#   HOME: sessions live in $HOME/.local/share/goose/sessions/sessions.db, so --resume works later
#   GOOSE_MODE: approve tool calls without asking
#   files AGENTS.md: the request's instructions, which goose reads from its working directory
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
base="${HI_PROVIDER_URL%/}"
export ANTHROPIC_HOST="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
export GOOSE_PROVIDER=anthropic GOOSE_MODEL="${HI_MODEL:-claude-sonnet-4-5}"
goose run --output-format stream-json ${HI_SESSION_ID:+-r --session-id "$HI_SESSION_ID"} -t "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
