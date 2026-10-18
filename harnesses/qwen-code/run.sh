#!/usr/bin/env bash
# Qwen Code, headless: positional prompt, stream-json output, yolo approvals. A follow-up passes
# --resume <session_id>; the chat file lives under $HOME/.qwen, keyed by the workspace path.
# Set in harness.json:
#   HOME: chats land under $HOME/.qwen/projects/<cwd>/chats, so --resume works later
#   QWEN_CODE_SUPPRESS_YOLO_WARNING: no warning about yolo approvals in the output
#   files QWEN.md: the request's instructions, under the only name qwen reads
set -euo pipefail
mkdir -p "$HOME"   # qwen refuses to start when HOME does not exist yet
export OPENAI_BASE_URL="${HI_PROVIDER_URL%/}" OPENAI_API_KEY="$HI_PROVIDER_KEY"
# qwen has no built-in default for an OpenAI-compatible endpoint, so the harness picks one.
export OPENAI_MODEL="${HI_MODEL:-deepseek-chat}"
qwen -o stream-json --approval-mode yolo ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
