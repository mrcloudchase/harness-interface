#!/usr/bin/env bash
# Cline CLI, headless, through its ACP mode: `cline -p` cannot resume (`--id` always opens the
# interactive UI), but ACP can load a saved session. `cline auth` saves the key as the anthropic
# provider's, under $HOME/.cline (inside .home/, never listed); CLINE_PROVIDER and CLINE_MODEL pick
# it for ACP sessions, and ACP starts a session only once CLINE_API_KEY is set. HI_PROVIDER_URL is
# ignored: the anthropic provider has no base URL setting.
# Set in harness.json:
#   HOME: the provider settings and the sessions live under $HOME/.cline, so a follow-up loads the session
#   files AGENTS.md: the request's instructions, which cline reads from its working directory
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
export CLINE_PROVIDER=anthropic CLINE_MODEL="${HI_MODEL:-claude-sonnet-4-5}" CLINE_API_KEY="$HI_PROVIDER_KEY"
cline auth anthropic -k "$HI_PROVIDER_KEY" -m "$CLINE_MODEL" >&2
python3 "$HI_HARNESS_DIR/acp.py" </dev/null | python3 "$HI_HARNESS_DIR/report.py"
