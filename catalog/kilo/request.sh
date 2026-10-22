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
export PWD="$HI_WORKSPACE" KILO_DISABLE_MODELS_FETCH=1 KILO_DISABLE_AUTOUPDATE=1 KILO_TELEMETRY_LEVEL=off KILO_PERMISSION='{"*":"allow"}'
export KILO_CONFIG_CONTENT=$(cat <<EOF
{"autoupdate": false, "share": "disabled", "enabled_providers": ["anthropic"], "experimental": {"openTelemetry": false},
 "provider": {"anthropic": {"options": {"baseURL": "${HI_PROVIDER_URL%/v1}/v1", "apiKey": "{env:ANTHROPIC_API_KEY}"}, "models": {"$HI_MODEL": {}}}},
 "model": "anthropic/$HI_MODEL", "small_model": "anthropic/$HI_MODEL"}
EOF
)
turn() {
  local args=(run --format json --auto -m "anthropic/$HI_MODEL")
  [ -f "$HI_DIR/turned" ] && args+=(-c)
  touch "$HI_DIR/turned"
  kilo "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
