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
export OPENSQUILLA_UPDATE_CHECK_DISABLED=1 ORT_DISABLE_TELEMETRY=1
mkdir -p "$HOME/.opensquilla"
cat > "$HOME/.opensquilla/config.toml" <<EOF
[llm]
provider = "anthropic"
model = "$HI_MODEL"
api_key_env = "ANTHROPIC_API_KEY"
base_url = "${HI_PROVIDER_URL%/v1}"
[squilla_router]
enabled = false
EOF
turn() { opensquilla agent -m "$1" --json --permissions bypass --workspace "$HI_WORKSPACE" --stateless-keep-project-rules --session-id "$HI_SESSION" --session-db-path "$HOME/.opensquilla/sessions.db"; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
