#!/usr/bin/env bash
# harness.py from the harness-engineering course, as a one-off request. Its one dependency, the
# Anthropic SDK, is in the default sandbox, so it runs with plain python3 and needs no network
# beyond its provider.
# It has no instruction file, so the request's instructions are prepended to the task. It runs its
# commands from the current directory, which is the workspace. The Anthropic SDK reads the two
# variables below.
set -euo pipefail
export ANTHROPIC_BASE_URL="${HI_PROVIDER_URL%/}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
task="$(python3 -c 'import json,os; r=json.load(open(os.environ["HI_REQUEST"])); i=(r.get("instructions") or "").strip(); print((i+"\n\n" if i else "")+r["task"])')"
python3 "$HI_HARNESS_DIR/harness.py" "$task" 2>&1 | python3 "$HI_HARNESS_DIR/report.py"
