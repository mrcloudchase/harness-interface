#!/usr/bin/env bash
# The probe "harness": no CLI; the adapter probes the network from inside the run container.
set -euo pipefail
cd "$HI_WORKSPACE"
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
