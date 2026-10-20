#!/usr/bin/env bash
# pi: no network but the provider (PI_OFFLINE drops pi.dev catalog/version/telemetry calls), then the
# adapter, which writes models.json (base URL + key-file command) and drives `pi --mode rpc`.
set -euo pipefail
cd "$HI_WORKSPACE"
export PI_OFFLINE=1 PI_TELEMETRY=0 PI_SKIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
