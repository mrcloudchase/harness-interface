#!/usr/bin/env bash
# Records where the install container can go (it should reach only install.egress) and that it
# holds no provider settings. No CLI.
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
env | grep -c '^HI_PROVIDER' > "$HI_TOOLS/provider_vars.txt" || true
python3 "$HI_HARNESS_DIR/egress_probe.py" registry.npmjs.org api.anthropic.com pypi.org github.com > "$HI_TOOLS/install_egress.json"
