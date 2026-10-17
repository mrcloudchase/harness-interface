#!/usr/bin/env bash
# ZeroClaw: write its config for this provider, then run one ACP turn through driver.py.
set -euo pipefail
cfg="$HOME/.zeroclaw"; mkdir -p "$cfg" "$cfg/agent"
cat > "$cfg/config.toml" <<CFG
schema_version = 3

[providers.models.custom.hi]
uri = "${HI_PROVIDER_URL%/}"
model = "${HI_MODEL:-deepseek-chat}"
native_tools = true

[agents.zeroclaw]
enabled = true
model_provider = "custom.hi"
risk_profile = "hi"
runtime_profile = "hi"

[agents.zeroclaw.workspace]
path = "$cfg/agent"

[risk_profiles.hi]
level = "full"
allowed_commands = ["*"]
block_high_risk_commands = false
workspace_only = false
forbidden_paths = []
allowed_tools = ["shell", "file_read", "file_write", "file_edit", "glob_search", "content_search", "web_fetch"]

[runtime_profiles.hi]
CFG
export ZEROCLAW_providers__models__custom__hi__api_key="$HI_PROVIDER_KEY"   # the key stays out of the file
python3 "$HI_HARNESS_DIR/driver.py" "$cfg" | python3 "$HI_HARNESS_DIR/report.py"
