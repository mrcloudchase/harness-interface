#!/usr/bin/env bash
# Decides what the response carries. Runs after request.sh with HG_STDOUT and HG_STDERR (paths to its
# streams), HG_EXIT (its exit code) and HG_OUTCOME (exited | cancelled). Print the response; exit 0
# for completed, anything else for failed. Delete this file to return request.sh's stdout as is.
set -u
if [ "$HG_OUTCOME" = "cancelled" ]; then
  printf 'cancelled after %s lines\n' "$(wc -l < "$HG_STDOUT")"
  exit 0
fi
tail -n 1 "$HG_STDOUT"            # for example: the CLI's last line is its answer
exit "$HG_EXIT"
