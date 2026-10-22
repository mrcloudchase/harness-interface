#!/usr/bin/env bash
# request.sh: one turn. The prompt is on stdin; stdout is relayed live and kept for response.sh.
# A steer arrives as $HI_DIR/interrupt plus the package's signal, delivered to this script alone,
# so the trap below runs the steer as the next turn once the current one ends.
set -uo pipefail
prompt=$(cat)
sid_uuid() { local h=${HI_SESSION#sess_}; echo "${h:0:8}-${h:8:4}-${h:12:4}-${h:16:4}-${h:20:12}"; }
run_wait() {   # run a turn and wait for it, re-waiting after a signal interrupts the wait
  "$@" </dev/null & local pid=$! rc
  while :; do wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null || break; done
  return $rc
}
steer=""
trap 'steer=$(cat "$HI_DIR/interrupt" 2>/dev/null || true)' USR1
mkdir -p "$HI_DIR/zc"
cat > "$HI_DIR/zc/config.toml" <<EOF
schema_version = 3
[providers.models.custom.hi]
uri = "${HI_PROVIDER_URL%/}"
model = "$HI_MODEL"
native_tools = true
[agents.zeroclaw]
enabled = true
model_provider = "custom.hi"
risk_profile = "hi"
[agents.zeroclaw.workspace]
path = "$HI_WORKSPACE"
[risk_profiles.hi]
level = "full"
allowed_commands = ["*"]
block_high_risk_commands = false
workspace_only = false
forbidden_paths = []
EOF
turn() { zeroclaw agent --agent zeroclaw --config-dir "$HI_DIR/zc" -m "$1" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
