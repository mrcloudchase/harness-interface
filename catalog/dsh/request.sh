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
export DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL%/v1}" DSH_TELEMETRY_DISABLED=1 DSH_PERMISSION_MODE=danger-full-access
cat > "$HI_DIR/patch.yml" <<EOF
- id: agent-default-model
  config: {provider: deepseek-official, model: $HI_MODEL}
EOF
turn() {
  local args=(--profile headless --patch "$HI_DIR/patch.yml" --json)
  [ -s "$HI_DIR/session" ] && args+=(--session-id "$(cat "$HI_DIR/session")")
  dsh "${args[@]}" "$1" </dev/null | tee "$HI_DIR/last.jsonl"
  local rc=${PIPESTATUS[0]}
  grep -o '"sessionId":"[^"]*"' "$HI_DIR/last.jsonl" | head -1 | cut -d'"' -f4 > "$HI_DIR/session.new" && [ -s "$HI_DIR/session.new" ] && mv "$HI_DIR/session.new" "$HI_DIR/session"
  return $rc
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
