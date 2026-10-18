#!/usr/bin/env bash
# Claude Code, headless. Everything specific to this CLI lives in this folder.
# The server gives HI_TASK, HI_MODEL, HI_SESSION_ID, HI_OUTPUT, HI_HARNESS_DIR, HI_PROVIDER_URL, HI_PROVIDER_KEY.
# Set in harness.json:
#   HOME: transcripts land inside the workspace, so --resume works later
#   IS_SANDBOX: claude refuses --dangerously-skip-permissions as root without this
#   files AGENTS.md: the request's instructions, which claude reads from its working directory
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
# The CLI appends /v1/messages itself, so the provider URL must not end in /v1.
base="${HI_PROVIDER_URL%/}"
export ANTHROPIC_BASE_URL="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY" ANTHROPIC_AUTH_TOKEN="$HI_PROVIDER_KEY"
claude -p "$HI_TASK" --output-format stream-json --verbose --dangerously-skip-permissions \
  ${HI_MODEL:+--model "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} \
  | python3 "$HI_HARNESS_DIR/report.py"
