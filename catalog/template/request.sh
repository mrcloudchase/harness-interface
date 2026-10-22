#!/usr/bin/env bash
# One turn. The prompt is on stdin; stdout is relayed live to a streaming client and kept in
# $HI_STDOUT for response.sh; stderr is kept in $HI_STDERR. Exit 0 when the turn went well.
#
# The platform sets: HI_WORKSPACE (cwd, kept between turns), HOME (seeded, kept per member),
# HI_DIR (scratch; $HI_DIR/interrupt holds a steer's text), HI_SESSION, HI_RESPONSE, HI_TURN (1, 2…),
# HI_MODEL, HI_INSTRUCTIONS, HI_REQUEST (the request body as JSON), HI_PROVIDER_URL and
# HI_PROVIDER_KEY_FILE (the gateway and the session token), plus the provider_env names above.
set -uo pipefail
prompt=$(cat)
run_wait() {   # run a turn and wait for it, re-waiting after a signal interrupts the wait
  "$@" </dev/null & local pid=$! rc
  while :; do wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null || break; done
  return $rc
}
steer=""
trap 'steer=$(cat "$HI_DIR/interrupt" 2>/dev/null || true)' USR1   # a steer: delivered to this script alone
turn() {
  # Replace with the CLI: resume on later turns ($HI_TURN -gt 1), pass "$1" as the task, point it at
  # $HI_PROVIDER_URL with the token in $OPENAI_API_KEY (or whatever provider_env names).
  echo-cli "turn $HI_TURN model=$HI_MODEL: $1"
}
run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
