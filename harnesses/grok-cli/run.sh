#!/usr/bin/env bash
# Grok Build, headless: -p one prompt, --output-format streaming-json (ACP updates, one per line).
# The provider is a custom model written into config.toml on every turn; the key stays in the
# environment (env_key), never in the file. A follow-up passes --resume <session_id>.
set -euo pipefail
mkdir -p "$HOME/.grok"
cat > "$HOME/.grok/config.toml" <<CFG
[models]
default = "hi"
[model.hi]
model = "${HI_MODEL:-deepseek-chat}"
base_url = "${HI_PROVIDER_URL%/}"
env_key = "HI_PROVIDER_KEY"
api_backend = "chat_completions"
context_window = 128000
CFG
grok -p "$HI_TASK" -m hi --output-format streaming-json --permission-mode bypassPermissions \
  ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} | python3 "$HI_HARNESS_DIR/report.py"
