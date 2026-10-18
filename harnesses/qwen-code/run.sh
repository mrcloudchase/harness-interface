#!/usr/bin/env bash
# Qwen Code, headless: positional prompt, stream-json output, yolo approvals. A follow-up passes
# --resume <session_id>; the chat file lives under $HOME/.qwen, keyed by the workspace path.
# Set in harness.json:
#   HOME: chats land under $HOME/.qwen/projects/<cwd>/chats, so --resume works later
#   QWEN_CODE_SUPPRESS_YOLO_WARNING: no warning about yolo approvals in the output
#   files QWEN.md: the request's instructions, under the only name qwen reads
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
mkdir -p "$HOME"   # qwen refuses to start when HOME does not exist yet
export OPENAI_BASE_URL="${HI_PROVIDER_URL%/}" OPENAI_API_KEY="$HI_PROVIDER_KEY"
# qwen has no built-in default for an OpenAI-compatible endpoint, so the harness picks one.
export OPENAI_MODEL="${HI_MODEL:-deepseek-chat}"
qwen -o stream-json --approval-mode yolo ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
