#!/usr/bin/env bash
# Maps the HI_* contract onto OpenCode's settings, then execs the adapter. The provider (base URL,
# key *file* reference, model) is per request, so adapter.py builds it into OPENCODE_CONFIG_CONTENT;
# the static config is home/.config/opencode/opencode.json.
set -euo pipefail
cd "$HI_WORKSPACE"                       # opencode resolves its directory from $PWD, not getcwd()
export PWD="$HI_WORKSPACE"
export OPENCODE_DISABLE_MODELS_FETCH=1 \
       OPENCODE_DISABLE_AUTOUPDATE=1 \
       OPENCODE_DISABLE_LSP_DOWNLOAD=1 \
       OPENCODE_DISABLE_DEFAULT_PLUGINS=1 \
       OPENCODE_DISABLE_CLAUDE_CODE=1 \
       OPENCODE_DISABLE_EMBEDDED_WEB_UI=1 \
       npm_config_offline=true            # its unconditional background `npm install @opencode-ai/plugin` into ~/.config/opencode: fail fast, no registry
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
