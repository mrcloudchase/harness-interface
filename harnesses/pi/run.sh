#!/usr/bin/env bash
# pi reads no base-URL variable, so the adapter writes $HOME/.pi/agent/models.json before every
# response (the URL as given, and `!cat` of the key file, so the key's value is never in pi's
# environment, argv or files). Here only the quiet switches.
set -euo pipefail
cd "$HI_WORKSPACE"
export PYTHONDONTWRITEBYTECODE=1                 # nothing written into the folder or the workspace
export PI_OFFLINE=1                              # no pi.dev catalog, version check or telemetry: the provider only
export PI_TELEMETRY=0 PI_SKIP_VERSION_CHECK=1
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
