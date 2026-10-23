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
export ANTHROPIC_BASE_URL="${HG_PROVIDER_URL%/v1}/v1" JCODE_NO_TELEMETRY=1 JCODE_RUN_AUTO_POKE=0 JCODE_RUNTIME_DIR=/tmp/jcode-rt
turn() {
  local args=(run --ndjson --no-update -p anthropic-api)
  [ -s "$HG_DIR/session" ] && args+=(--resume "$(cat "$HG_DIR/session")")
  [ -n "$HG_MODEL" ] && [ ! -s "$HG_DIR/session" ] && args+=(-m "$HG_MODEL")
  jcode "${args[@]}" "$1" | tee "$HG_DIR/last.jsonl"
  local rc=${PIPESTATUS[0]}
  grep -o '"session_id":"[^"]*"' "$HG_DIR/last.jsonl" | head -1 | cut -d'"' -f4 > "$HG_DIR/session.new" && [ -s "$HG_DIR/session.new" ] && mv "$HG_DIR/session.new" "$HG_DIR/session"
  return $rc
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
