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
export OPENAI_MODEL="$HG_MODEL" QWEN_CODE_SUPPRESS_YOLO_WARNING=1 QWEN_CODE_MODELS_DEV=off QWEN_USAGE_STATISTICS_ENABLED=0
turn() {
  local args=(--approval-mode yolo --auth-type openai -m "$HG_MODEL" -o stream-json)
  if [ -f "$HG_DIR/turned" ]; then args+=(--resume "$(sid_uuid)"); else args+=(--session-id "$(sid_uuid)"); fi
  touch "$HG_DIR/turned"
  qwen "${args[@]}" "$1" </dev/null
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
