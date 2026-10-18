#!/usr/bin/env bash
# Hermes Agent, headless: -q one query, -Q quiet (final answer only), --yolo no approvals.
# It prints the answer on stdout and "session_id: ..." on stderr, so both go through the reporter.
# Set in harness.json:
#   HERMES_HOME: config, auth and the session database, so --resume works later
#   HOME: the CLI's home, inside the workspace's .home
#   files AGENTS.md: the request's instructions, which hermes reads from its working directory
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
export ANTHROPIC_BASE_URL="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
hermes chat -q "$HI_TASK" -Q --yolo --accept-hooks --provider anthropic \
  ${HI_MODEL:+-m "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} 2>&1 \
  | python3 "$HI_HARNESS_DIR/report.py"
