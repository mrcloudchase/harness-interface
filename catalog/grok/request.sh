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
export GROK_FOLDER_TRUST=0 GROK_DISABLE_AUTOUPDATER=1
mkdir -p "$HOME/.grok"
cat > "$HOME/.grok/config.toml" <<EOF
[models]
session_summary = "hg"
prompt_suggestion = "hg"
[model.hg]
model = "$HG_MODEL"
base_url = "${HG_PROVIDER_URL%/}"
env_key = "OPENAI_API_KEY"
api_backend = "chat_completions"
EOF
turn() {
  local args=(-p "$1" -m hg --output-format streaming-json --permission-mode bypassPermissions)
  if [ -f "$HG_DIR/turned" ]; then args+=(--resume "$(sid_uuid)"); else args+=(-s "$(sid_uuid)"); fi
  touch "$HG_DIR/turned"
  grok "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
