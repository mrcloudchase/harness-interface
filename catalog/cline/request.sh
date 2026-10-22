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
export CLINE_SESSION_BACKEND_MODE=local CLINE_NO_AUTO_UPDATE=1
mkdir -p "$HOME/.cline/data/settings"
cat > "$HOME/.cline/data/settings/providers.json" <<EOF
{"version": 1, "lastUsedProvider": "openai-compatible", "modes": {},
 "providers": {"openai-compatible": {"settings": {"provider": "openai-compatible", "apiKey": "$OPENAI_API_KEY", "model": "$HI_MODEL", "baseUrl": "${HI_PROVIDER_URL%/}"},
                                     "updatedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "tokenSource": "manual"}}}
EOF
turn() { cline --json -y "$1" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
