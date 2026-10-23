#!/usr/bin/env bash
# request.sh: one turn. The prompt is on stdin; stdout is relayed live and kept for response.sh.
# A steer arrives as $HG_DIR/interrupt plus the package's signal, delivered to this script alone,
# so the trap below runs the steer as the next turn once the current one ends.
set -uo pipefail
prompt=$(cat)
sid_uuid() { local h=${HG_SESSION#sess_}; echo "${h:0:8}-${h:8:4}-${h:12:4}-${h:16:4}-${h:20:12}"; }
run_wait() {   # run a turn and wait for it, re-waiting after a signal interrupts the wait
  "$@" </dev/null & local pid=$! rc
  while :; do wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null || break; done
  return $rc
}
steer=""
trap 'steer=$(cat "$HG_DIR/interrupt" 2>/dev/null || true)' USR1
export MIMOCODE_DISABLE_AUTOUPDATE=1 MIMOCODE_DISABLE_MODELS_FETCH=1 MIMOCODE_ENABLE_ANALYSIS=0
export MIMOCODE_CONFIG_CONTENT=$(cat <<EOF
{"provider": {"anthropic": {"options": {"baseURL": "${HG_PROVIDER_URL%/v1}/v1"}, "models": {"$HG_MODEL": {}}}}, "model": "anthropic/$HG_MODEL"}
EOF
)
turn() {
  local args=(run --format json -m "anthropic/$HG_MODEL")
  [ -f "$HG_DIR/turned" ] && args+=(-c)
  touch "$HG_DIR/turned"
  mimo "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
