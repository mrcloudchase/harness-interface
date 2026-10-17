#!/usr/bin/env bash
# harness.py from the harness-engineering course, as a one-off request: `uv run harness.py "<task>"`.
# It has no instruction file, so the request's instructions are prepended to the task. It runs its
# commands from the current directory, which is the workspace.
set -euo pipefail
py="${HARNESS_ENGINEERING:?set HARNESS_ENGINEERING to your harness-engineering checkout}/harness.py"
[ -f "$py" ] || { echo "harness.py not found at $py" >&2; exit 2; }
task="$(python3 -c 'import json,os; r=json.load(open(os.environ["HI_REQUEST"])); i=(r.get("instructions") or "").strip(); print((i+"\n\n" if i else "")+r["task"])')"
uv run -q "$py" "$task" 2>&1 | python3 "$HI_HARNESS_DIR/report.py"
