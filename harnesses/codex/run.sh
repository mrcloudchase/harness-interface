#!/usr/bin/env bash
# Codex CLI, headless. A follow-up resumes the most recent session in this workspace's CODEX_HOME.
# Set in harness.json:
#   CODEX_HOME: sessions live here, so `resume --last` is this conversation's
#   HOME: the CLI's home, inside the workspace's .home
#   files AGENTS.md: the request's instructions, which codex reads from its working directory
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
