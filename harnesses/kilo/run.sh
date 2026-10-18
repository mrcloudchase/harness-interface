#!/usr/bin/env bash
# Kilo Code CLI (OpenCode fork), headless: `run --format json` emits one event per line, `--auto` approves tool calls,
# `-s <id>` continues a session stored under $HOME. Models are named provider/model.
# Set in harness.json:
#   HOME: sessions live in $HOME/.local/share/kilo/kilo.db, so --session resumes later
#   files AGENTS.md: the request's instructions, which kilo reads from its working directory
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
# The anthropic provider appends /messages itself, so the base URL must end in /v1.
base="${HI_PROVIDER_URL%/}"
export KILO_CONFIG_CONTENT="{\"provider\":{\"anthropic\":{\"options\":{\"baseURL\":\"${base%/v1}/v1\"}}}}"
model="${HI_MODEL:-claude-sonnet-4-5}"; [[ "$model" == */* ]] || model="anthropic/$model"
kilo run --format json --auto -m "$model" ${HI_SESSION_ID:+-s "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
