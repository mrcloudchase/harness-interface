#!/usr/bin/env bash
# pi, headless: -p one prompt, --mode json one event per line. A follow-up reopens the same
# session id, which pi creates on first use.
# Set in harness.json:
#   HOME: sessions land under $HOME/.pi/agent/sessions, so --session-id resumes later
#   files AGENTS.md: the request's instructions, which pi reads from its working directory
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
# pi wants --model whenever --provider is given, so the harness picks a default model.
pi -p --mode json --provider anthropic --model "${HI_MODEL:-claude-sonnet-5-5}" \
  ${HI_SESSION_ID:+--session-id "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
