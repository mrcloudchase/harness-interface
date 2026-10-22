#!/usr/bin/env bash
# Decides what the response carries. Runs after request.sh with HI_STDOUT and HI_STDERR (paths to its
# streams), HI_EXIT (its exit code) and HI_OUTCOME (exited | cancelled). Print the response; exit 0
# for completed, anything else for failed. Delete this file to return request.sh's stdout as is.
set -u
if [ "$HI_OUTCOME" = "cancelled" ]; then
  printf 'cancelled after %s lines\n' "$(wc -l < "$HI_STDOUT")"
  exit 0
fi
tail -n 1 "$HI_STDOUT"            # for example: the CLI's last line is its answer
exit "$HI_EXIT"
