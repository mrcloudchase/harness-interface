#!/usr/bin/env bash
# Maps the HI_* contract onto the CLI's own settings, then execs the adapter (one process, so the
# server's SIGINT reaches it). Quiet switches, base-URL rules and key handling live here.
set -euo pipefail
cd "$HI_WORKSPACE"
export PYTHONDONTWRITEBYTECODE=1                 # nothing written into the folder or the workspace
export STANDIN_DELAY="${STANDIN_DELAY:-0.3}"
if [ -n "${HI_PROVIDER_URL:-}" ]; then
  # Hand the CLI the key file's path, never its value: the file holds the session's token under the
  # gateway, or the key in file mode, and the adapter never needs to know which.
  export STANDIN_BASE_URL="$HI_PROVIDER_URL" STANDIN_API="$HI_PROVIDER_API" STANDIN_API_KEY_FILE="$HI_PROVIDER_KEY_FILE"
fi
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
