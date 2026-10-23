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
export GOOSE_PROVIDER=anthropic GOOSE_MODEL="$HG_MODEL" ANTHROPIC_HOST="${HG_PROVIDER_URL%/v1}" GOOSE_DISABLE_SESSION_NAMING=1 RUST_BACKTRACE=0
export GOOSE_MODE=auto
turn() {
  local args=(run -t "$1" --output-format stream-json -n "$HG_SESSION")
  [ -f "$HG_DIR/turned" ] && args+=(-r)
  touch "$HG_DIR/turned"
  goose "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
