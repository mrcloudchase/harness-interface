#!/usr/bin/env bash
# One turn. The prompt is on stdin; stdout is relayed live to a streaming client and kept in
# $HG_STDOUT for response.sh; stderr is kept in $HG_STDERR. Exit 0 when the turn went well.
#
# The platform sets: HG_WORKSPACE (cwd, kept between turns), HOME (seeded, kept per member),
# HG_DIR (scratch; $HG_DIR/interrupt holds a steer's text), HG_SESSION, HG_RESPONSE, HG_TURN (1, 2…),
# HG_MODEL, HG_INSTRUCTIONS, HG_REQUEST (the request body as JSON), HG_PROVIDER_URL and
# HG_PROVIDER_KEY_FILE (the gateway and the session token), plus the provider_env names above.
set -uo pipefail
prompt=$(cat)
run_wait() {   # run a turn and wait for it, re-waiting after a signal interrupts the wait
  "$@" </dev/null & local pid=$! rc
  while :; do wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null || break; done
  return $rc
}
steer=""
trap 'steer=$(cat "$HG_DIR/interrupt" 2>/dev/null || true)' USR1   # a steer: delivered to this script alone
turn() {
  # Replace with the CLI: resume on later turns ($HG_TURN -gt 1), pass "$1" as the task, point it at
  # $HG_PROVIDER_URL with the token in $OPENAI_API_KEY (or whatever provider_env names).
  echo-cli "turn $HG_TURN model=$HG_MODEL: $1"
}
run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
