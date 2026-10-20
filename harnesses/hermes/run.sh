#!/usr/bin/env bash
# Maps HI_* onto Hermes's own settings, then execs the adapter, which runs `hermes acp`. The key's
# value is never in an environment: the adapter starts hermes on a launcher that reads
# $HI_PROVIDER_KEY_FILE inside hermes's own process (the key, or under the gateway the session's token).
set -euo pipefail
cd "$HI_WORKSPACE"
export PYTHONDONTWRITEBYTECODE=1                     # nothing written into the folder or the workspace
export HERMES_HOME="$HOME/.hermes"                   # its sessions (state.db), logs, memories and caches
export TIRITH_ENABLED=0                              # no 38 MB tirith download from github.com
export HERMES_YOLO_MODE=1 HERMES_ACCEPT_HOOKS=1      # no approval prompts for commands or the folder's hooks
unset ANTHROPIC_TOKEN CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY   # the first two outrank the key in hermes
# config.yaml's model block: the provider's URL as the shape's SDK takes it, pinned (else the ACP model
# list calls api.anthropic.com with the key, whatever the provider), and the request's model.
export HERMES_BASE_URL="${HI_PROVIDER_URL:-https://api.anthropic.com}"
export HERMES_INFERENCE_MODEL="${HI_MODEL:-claude-sonnet-4-6}"
case "${HI_PROVIDER_API:-anthropic-messages}" in
  anthropic-messages)
    export HERMES_INFERENCE_PROVIDER=anthropic HERMES_API_MODE=anthropic_messages
    export ANTHROPIC_BASE_URL="$HERMES_BASE_URL" ;;    # no /v1: hermes appends it
  openai-chat)
    export HERMES_INFERENCE_PROVIDER=custom HERMES_API_MODE=chat_completions ;;
  *) echo "run.sh: hermes does not speak $HI_PROVIDER_API" >&2; exit 2 ;;
esac
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
