#!/usr/bin/env bash
# Aider, headless: --message one prompt then exit, --yes-always no confirmations, plain unstreamed
# text. History files are kept under $HOME so they are never "produced"; a follow-up restores
# that chat history (the session handle is just the constant "chat-history"). Git stays on for the
# repo map, but aider must not commit or touch .gitignore: the server diffs the workspace itself.
# Set in harness.json:
#   HOME: .aider* history files and caches live here, so --restore-chat-history works later
#   LITELLM_LOCAL_MODEL_COST_MAP: use the bundled price map; the sandbox reaches only the provider
#   AIDER_CHECK_UPDATE: no update check; the sandbox reaches only the provider
#   files AGENTS.md: the request's instructions; aider reads no instruction file, so this script passes it with --read
set -euo pipefail
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY" ANTHROPIC_API_BASE="${HI_PROVIDER_URL%/}"
# aider fetches litellm's price map from GitHub whenever its own cache is empty or a day old, and
# prints the failure into its answer. A fresh, non-empty cache stops the fetch; prices then come
# from the map litellm bundles.
mkdir -p "$HOME/.aider/caches"; echo '{"_": {}}' > "$HOME/.aider/caches/model_prices_and_context_window.json"
if [ -d "$HI_WORKSPACE/.git" ]; then   # aider nags without a git identity, and drops its tags cache in the repo root
  git -C "$HI_WORKSPACE" config user.name aider; git -C "$HI_WORKSPACE" config user.email aider@localhost
  grep -qsx '.aider*' "$HI_WORKSPACE/.git/info/exclude" || echo '.aider*' >> "$HI_WORKSPACE/.git/info/exclude"
fi
model="${HI_MODEL:-claude-sonnet-4-5}"; [[ "$model" == */* ]] || model="anthropic/$model"
# aider has no instruction file of its own; --read puts AGENTS.md in the chat as read-only context.
context=(); [ -s AGENTS.md ] && context=(--read AGENTS.md)
aider --model "$model" --message "$HI_TASK" "${context[@]}" --yes-always --no-pretty --no-stream \
  --no-auto-commits --no-dirty-commits --no-gitignore --no-show-model-warnings \
  --no-check-update --no-show-release-notes --analytics-disable \
  --chat-history-file "$HOME/.aider.chat.history.md" --input-history-file "$HOME/.aider.input.history" \
  --llm-history-file "$HOME/.aider.llm.history" ${HI_SESSION_ID:+--restore-chat-history} \
  | python3 "$HI_HARNESS_DIR/report.py"
