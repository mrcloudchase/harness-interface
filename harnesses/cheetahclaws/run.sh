#!/usr/bin/env bash
# CheetahClaws. Its -p mode cannot resume, so the REPL is fed on stdin instead: an optional
# "/resume <id>", the task, then "/exit", which saves the session and prints its id.
# The custom provider is the only one with a configurable base URL; the model is "custom/<name>".
# Set in harness.json:
#   HOME: sessions land under $HOME/.cheetahclaws/sessions, so /resume works later
#   CHEETAH_PT_INPUT: plain readline input, no prompt_toolkit
#   files CLAUDE.md: the request's instructions, under the only name cheetahclaws reads
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
mkdir -p "$HOME"   # cheetahclaws creates ~/.cheetahclaws but not its parent
export CUSTOM_BASE_URL="${HI_PROVIDER_URL%/}" CUSTOM_API_KEY="$HI_PROVIDER_KEY"
{ [ -n "${HI_SESSION_ID:-}" ] && printf '/resume %s\n' "$HI_SESSION_ID"; printf '%s\n/exit\n' "$HI_TASK"; } \
  | cheetahclaws --accept-all -m "custom/${HI_MODEL:-gpt-4.1-mini}" \
  | python3 "$HI_HARNESS_DIR/report.py"
