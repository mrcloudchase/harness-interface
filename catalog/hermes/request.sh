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
export HERMES_HOME="$HOME/.hermes" TIRITH_ENABLED=0 HERMES_YOLO_MODE=1 HERMES_INFERENCE_PROVIDER=anthropic
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL%/v1}"
mkdir -p "$HERMES_HOME"
cat > "$HERMES_HOME/config.yaml" <<EOF
model:
  provider: anthropic
  base_url: ${ANTHROPIC_BASE_URL}
  default: ${HI_MODEL}
  context_length: 128000
security:
  tirith_enabled: false
memory:
  nudge_interval: 0
skills:
  creation_nudge_interval: 0
agent:
  verify_on_stop: false
EOF
turn() {
  local args=(chat -q "$1" --yolo --provider anthropic -m "$HI_MODEL" --no-restore-cwd)
  [ -s "$HI_DIR/session" ] && args+=(--resume "$(cat "$HI_DIR/session")")
  hermes "${args[@]}" | tee "$HI_DIR/out"
  local rc=${PIPESTATUS[0]}
  sed -n 's/^Session: *//p' "$HI_DIR/out" | tail -1 > "$HI_DIR/session.new" && [ -s "$HI_DIR/session.new" ] && mv "$HI_DIR/session.new" "$HI_DIR/session"
  return $rc
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
