#!/usr/bin/env bash
# J-Code, headless. A resumed session keeps the model it started with: jcode refuses -m on resume.
# Set in harness.json:
#   HOME: sessions live under $HOME/.jcode, so --resume works later
#   JCODE_NO_TELEMETRY: no telemetry; the sandbox reaches only the provider
#   files AGENTS.md: the request's instructions, which jcode reads from its working directory
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
base="${HI_PROVIDER_URL%/}"   # jcode appends /messages, so the base carries /v1
export ANTHROPIC_BASE_URL="${base%/v1}/v1" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
if [ -n "${HI_SESSION_ID:-}" ]; then
  jcode run --json -p anthropic-api --resume "$HI_SESSION_ID" "$HI_TASK"
else
  jcode run --json -p anthropic-api -m "${HI_MODEL:-claude-sonnet-4-5}" "$HI_TASK"
fi | python3 "$HI_HARNESS_DIR/report.py"
