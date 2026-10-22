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
mkdir -p "$HOME/.nanobot"
cat > "$HOME/.nanobot/config.json" <<EOF
{"providers": {"anthropic": {"apiKey": "\${ANTHROPIC_API_KEY}", "apiBase": "\${ANTHROPIC_BASE_URL}"}},
 "agents": {"defaults": {"provider": "anthropic", "model": "anthropic/$HI_MODEL", "workspace": "$HI_WORKSPACE"}}}
EOF
turn() { nanobot agent --no-markdown -m "$1" -s "$HI_SESSION" -w "$HI_WORKSPACE" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
