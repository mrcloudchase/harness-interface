#!/usr/bin/env bash
# DeepSeek Harness, headless. `--json` emits NDJSON run events; `--session-id` resumes a session
# persisted under $HOME/.dsh.
# Set in harness.json:
#   HOME: dsh keeps profiles and sessions under $HOME/.dsh, so resume works later
#   DSH_TELEMETRY_DISABLED: no telemetry; the sandbox reaches only the provider
#   files AGENTS.md: the request's instructions, which dsh reads from its working directory
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
export DEEPSEEK_BASE_URL="${HI_PROVIDER_URL%/}" DEEPSEEK_API_KEY="$HI_PROVIDER_KEY"
[ -n "${HI_MODEL:-}" ] && export DEEPSEEK_DEFAULT_MODEL="$HI_MODEL"
dsh --profile headless --json ${HI_SESSION_ID:+--session-id "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
