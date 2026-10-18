#!/usr/bin/env bash
# harness.py from the harness-engineering course, as a one-off request. Its one dependency, the
# Anthropic SDK, is in the default sandbox, so it runs with plain python3 and needs no network
# beyond its provider. It runs its commands from the current directory, which is the workspace.
# It has no instruction file, so the request's instructions are prepended to the task. It keeps
# its conversation in memory only, so report.py keeps a transcript of each turn in $HOME, and a
# follow-up hands harness.py the earlier turns first, the way it hands itself a summary when its
# context fills.
# Set in harness.json:
#   HOME: conversation.txt, the transcript a follow-up continues from
set -euo pipefail
# Artifacts: each line of this folder's optional `artifacts` file names a file in the folder and
# where it goes under $HOME, as `review.md .claude/skills/review/SKILL.md`. Each is put in place
# before every turn; blank lines and lines starting with # are skipped.
if [ -f "$HI_HARNESS_DIR/artifacts" ]; then
  while read -r src dest _ || [ -n "${src:-}" ]; do
    case "$src" in ''|'#'*) continue ;; esac
    case "$src" in */*) echo "artifacts: $src is not a file in this folder" >&2; exit 2 ;; esac
    case "/$dest/" in //|*//*|*/../*|*/./*) echo "artifacts: $dest is not a path under \$HOME" >&2; exit 2 ;; esac
    mkdir -p "$(dirname "$HOME/$dest")" && cp "$HI_HARNESS_DIR/$src" "$HOME/$dest"
  done < "$HI_HARNESS_DIR/artifacts"
fi
export ANTHROPIC_BASE_URL="${HI_PROVIDER_URL%/}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
task="$(python3 -c '
import json, os
r = json.load(open(os.environ["HI_REQUEST"]))
earlier = os.path.join(os.environ["HOME"], "conversation.txt")
parts = [(r.get("instructions") or "").strip(),
         "[the earlier conversation]\n" + open(earlier).read().strip() if r["session_id"] and os.path.exists(earlier) else "",
         r["task"]]
print("\n\n".join(p for p in parts if p))')"
python3 "$HI_HARNESS_DIR/harness.py" "$task" 2>&1 | python3 "$HI_HARNESS_DIR/report.py"
