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
mkdir -p "$HOME/.minimax"
cat > "$HG_DIR/mcode.yaml" <<EOF
defaultModel: custom_provider:hg/$HG_MODEL
permissionMode: "off"
dataContribution:
  enabled: false
custom_provider:
  hg:
    kind: custom
    enabled: true
    api: anthropic-messages
    options:
      baseURL: ${HG_PROVIDER_URL%/v1}
      authMode: api-key
      apiKey: $ANTHROPIC_API_KEY
    models:
      $HG_MODEL: {}
EOF
turn() {
  local args=(exec --output-format stream-json --permission off --cwd "$HG_WORKSPACE" --config "$HG_DIR/mcode.yaml")
  [ -f "$HG_DIR/turned" ] && args+=(--continue)
  touch "$HG_DIR/turned"
  mcode "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
