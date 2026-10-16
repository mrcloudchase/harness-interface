#!/usr/bin/env bash
# Codex CLI, headless. A follow-up resumes the most recent session in this workspace's CODEX_HOME.
set -euo pipefail
flags=(--json --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check)
[ -n "${HI_MODEL:-}" ] && flags+=(-m "$HI_MODEL")
if [ -n "${HI_SESSION_ID:-}" ] && [ -d "$CODEX_HOME/sessions" ]; then
  codex exec resume --last "${flags[@]}" "$HI_TASK"
else
  codex exec "${flags[@]}" --cd "$HI_WORKSPACE" "$HI_TASK"
fi | python3 "$HI_HARNESS_DIR/report.py"
