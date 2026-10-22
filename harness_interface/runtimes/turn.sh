#!/usr/bin/env bash
# The turn, as the platform runs it inside the sandbox. Mounted read-only; the package never sees it.
#
#   request.sh   the prompt on stdin (from $HI_DIR/prompt); its stdout is relayed live and kept in
#                $HI_STDOUT, its stderr relayed and kept in $HI_STDERR; its exit code is $HI_EXIT
#   response.sh  runs after request.sh ends however it ended, with HI_STDOUT, HI_STDERR, HI_EXIT and
#                HI_OUTCOME (exited | cancelled); what it prints is the response, its exit code the
#                status. Without one, the response is request.sh's stdout and its exit code.
#
# A stop (SIGTERM) is passed to request.sh's whole process group; response.sh still runs, within the
# stop's grace. The steer signal ($HI_INTERRUPT) is delivered to request.sh alone, never to the CLI
# it runs, so a package handles a steer in one trap and nothing it starts has to.
set -u
cd "$HI_WORKSPACE"
export HI_STDOUT="$HI_DIR/stdout" HI_STDERR="$HI_DIR/stderr"
rm -f "$HI_DIR/.out" "$HI_DIR/.err" "$HI_DIR/response" "$HI_DIR/response.err"
: > "$HI_STDOUT"; : > "$HI_STDERR"
mkfifo "$HI_DIR/.out" "$HI_DIR/.err"
set -m
tee -a "$HI_STDOUT" < "$HI_DIR/.out" & out=$!
tee -a "$HI_STDERR" < "$HI_DIR/.err" >&2 & err=$!
outcome=exited
bash "$HI_HARNESS_DIR/request.sh" < "$HI_DIR/prompt" > "$HI_DIR/.out" 2> "$HI_DIR/.err" & pid=$!
trap 'outcome=cancelled; kill -TERM -- "-$pid" 2>/dev/null' TERM
trap 'kill -s "$HI_INTERRUPT" "$pid" 2>/dev/null' "$HI_INTERRUPT"
while :; do wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null || break; done
wait "$out" "$err" 2>/dev/null
trap - TERM "$HI_INTERRUPT"
rm -f "$HI_DIR/.out" "$HI_DIR/.err"
export HI_EXIT=$rc HI_OUTCOME=$outcome
if [ -f "$HI_HARNESS_DIR/response.sh" ]; then
  bash "$HI_HARNESS_DIR/response.sh" < /dev/null > "$HI_DIR/response" 2> "$HI_DIR/response.err"
  exit $?
fi
cp "$HI_STDOUT" "$HI_DIR/response"
exit "$rc"
