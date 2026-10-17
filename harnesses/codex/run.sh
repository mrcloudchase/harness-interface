#!/usr/bin/env bash
# Codex CLI, headless. A follow-up resumes the most recent session in this workspace's CODEX_HOME.
set -euo pipefail
mkdir -p "$CODEX_HOME"   # codex refuses to start when CODEX_HOME does not exist yet
export OPENAI_BASE_URL="${HI_PROVIDER_URL%/}"
# codex ignores OPENAI_API_KEY for its built-in provider; the key has to be logged in, which writes
# $CODEX_HOME/auth.json. That file is under .home/, which the server never lists or commits.
printf '%s' "$HI_PROVIDER_KEY" | codex login --with-api-key >/dev/null
flags=(--json --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check)
[ -n "${HI_MODEL:-}" ] && flags+=(-m "$HI_MODEL")
if [ -n "${HI_SESSION_ID:-}" ] && [ -d "$CODEX_HOME/sessions" ]; then
  codex exec resume --last "${flags[@]}" "$HI_TASK"
else
  codex exec "${flags[@]}" --cd "$HI_WORKSPACE" "$HI_TASK"
fi | python3 "$HI_HARNESS_DIR/report.py"
