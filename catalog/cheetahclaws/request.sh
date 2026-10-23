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
export CUSTOM_BASE_URL="${HG_PROVIDER_URL%/}" CHEETAH_PT_INPUT=0 CHEETAH_SUGGEST=0
mkdir -p "$HOME/.cheetahclaws"
[ -f "$HOME/.cheetahclaws/config.json" ] || echo '{"config_version": 2, "max_tokens": 0, "disabled_tools": ["AskUserQuestion", "EnterPlanMode", "ExitPlanMode"]}' > "$HOME/.cheetahclaws/config.json"
turn() { cheetahclaws -p "$1" -m "custom/$HG_MODEL" --accept-all </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
