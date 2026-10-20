#!/usr/bin/env bash
# Maps the HI_* contract onto the CLI's own settings, then execs the adapter (one process, so
# the runner's SIGINT reaches it). Quiet switches, base-URL rules and key handling live here.
set -euo pipefail
cd "$HI_WORKSPACE"
export STANDIN_DELAY="${STANDIN_DELAY:-0.3}"
if [ -n "${HI_PROVIDER_URL:-}" ]; then
  export STANDIN_BASE_URL="$HI_PROVIDER_URL" STANDIN_API="$HI_PROVIDER_API"
  # Prefer handing the CLI the key *file*; export the value under the CLI's own name only when
  # it cannot read a file (then it is in every child's environment).
  if [ -n "${HI_PROVIDER_KEY_FILE:-}" ]; then
    export STANDIN_API_KEY_FILE="$HI_PROVIDER_KEY_FILE"
  else                                   # only for `hirun.py --secret env` (rejected option a)
    export STANDIN_API_KEY="${HI_PROVIDER_KEY:-}"
  fi
fi
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
