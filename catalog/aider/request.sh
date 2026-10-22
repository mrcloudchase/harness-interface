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
export OPENAI_API_BASE="${HI_PROVIDER_URL%/}" LITELLM_LOCAL_MODEL_COST_MAP=True AIDER_ANALYTICS_DISABLE=1
turn() {
  local args=(--model "openai/$HI_MODEL" --message "$1" --yes-always --no-pretty --no-stream --no-git --no-fancy-input
              --no-show-model-warnings --no-check-update --no-show-release-notes --analytics-disable
              --chat-history-file "$HI_DIR/chat.history.md" --input-history-file "$HI_DIR/input.history" --llm-history-file "$HI_DIR/llm.history")
  [ -f "$HI_DIR/turned" ] && args+=(--restore-chat-history)
  touch "$HI_DIR/turned"
  aider "${args[@]}" </dev/null
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
