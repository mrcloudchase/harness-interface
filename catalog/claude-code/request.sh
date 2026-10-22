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
export IS_SANDBOX=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$HI_MODEL" ANTHROPIC_SMALL_FAST_MODEL="$HI_MODEL"
turn() {
  local args=(-p "$1" --output-format stream-json --verbose --dangerously-skip-permissions --model "$HI_MODEL")
  [ -n "${HI_INSTRUCTIONS:-}" ] && args+=(--append-system-prompt "$HI_INSTRUCTIONS")
  [ "$HI_TURN" -gt 1 ] || [ -f "$HI_DIR/turned" ] && args+=(--continue)
  touch "$HI_DIR/turned"
  claude "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
