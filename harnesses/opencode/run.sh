#!/usr/bin/env bash
# Maps HI_* onto OpenCode's settings, then execs the adapter. The provider (base URL, key file, model)
# is per request and JSON, so adapter.py writes it into OPENCODE_CONFIG_CONTENT; the static config is
# home/.config/opencode/opencode.json. The key's value is in no environment: OpenCode reads the file.
set -euo pipefail
cd "$HI_WORKSPACE"
export PWD="$HI_WORKSPACE"                           # opencode takes its directory from $PWD, not getcwd()
export PYTHONDONTWRITEBYTECODE=1                     # nothing written into the folder or the workspace
export OPENCODE_DISABLE_MODELS_FETCH=1               # the built-in catalog, not models.opencode.ai
export OPENCODE_DISABLE_AUTOUPDATE=1
export OPENCODE_DISABLE_LSP_DOWNLOAD=1
export OPENCODE_DISABLE_DEFAULT_PLUGINS=1            # its own auth plugins; the folder's plugins still load
export OPENCODE_DISABLE_CLAUDE_CODE=1                # no ~/.claude: only home/ and files shape it
export OPENCODE_DISABLE_EMBEDDED_WEB_UI=1
export npm_config_offline=true                       # its background `npm install @opencode-ai/plugin` fails at once
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
