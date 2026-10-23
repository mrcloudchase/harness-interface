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
export CODEX_HOME="$HOME/.codex"
mkdir -p "$CODEX_HOME"
cat > "$CODEX_HOME/config.toml" <<EOF
model_provider = "hg"
model = "$HG_MODEL"
approval_policy = "never"
sandbox_mode = "danger-full-access"
check_for_update_on_startup = false
[model_providers.hg]
name = "hg"
base_url = "${HG_PROVIDER_URL%/}"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
[features]
plugins = false
api_key_model_discovery = false
unbounded_connection_retries = false
[analytics]
enabled = false
EOF
turn() {
  if [ -s "$HG_DIR/thread" ]; then
    codex exec resume --json --skip-git-repo-check "$(cat "$HG_DIR/thread")" "$1"
  else
    codex exec --json --skip-git-repo-check -m "$HG_MODEL" "$1" | tee "$HG_DIR/last.jsonl"
    local rc=${PIPESTATUS[0]}
    grep -o '"thread_id":"[^"]*"' "$HG_DIR/last.jsonl" | head -1 | cut -d'"' -f4 > "$HG_DIR/thread"
    return $rc
  fi
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
