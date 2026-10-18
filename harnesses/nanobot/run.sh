#!/usr/bin/env bash
# nanobot, headless: `agent -m <message>` sends one message and exits; `-s <id>` names the session,
# which the harness mints on the first turn and reuses after. It has no env vars for the provider,
# so run.sh writes the key, base URL and model into $HOME/.nanobot/config.json (under .home/,
# which the server never lists). `onboard` creates that file and the workspace the first time.
# Its shell and file tools run inside that nanobot workspace ($HOME/.nanobot/workspace), not here:
# `-w "$HI_WORKSPACE"` would fix the cwd but bootstraps SOUL.md, memory/ and a .git store into it.
# Set in harness.json:
#   HOME: config and sessions live under $HOME/.nanobot, so -s <id> resumes later
#   COLUMNS: Rich hard-wraps the answer at 80 columns otherwise
#   files .home/.nanobot/workspace/AGENTS.md: the request's instructions, in the workspace nanobot works in
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
[ -f "$HOME/.nanobot/config.json" ] || nanobot onboard >/dev/null 2>&1
python3 - "$HI_PROVIDER_URL" "$HI_PROVIDER_KEY" "${HI_MODEL:-claude-sonnet-4-5}" <<'PY'
import json, os, sys
p = os.path.expanduser("~/.nanobot/config.json"); d = json.load(open(p))
d["providers"]["anthropic"].update(apiKey=sys.argv[2], apiBase=sys.argv[1].rstrip("/"))
d["agents"]["defaults"].update(provider="anthropic", model="anthropic/" + sys.argv[3].split("/")[-1])
json.dump(d, open(p, "w"), indent=2)
PY
chmod 600 "$HOME/.nanobot/config.json"   # it holds the provider key
session="${HI_SESSION_ID:-$(python3 -c 'import uuid; print(uuid.uuid4())')}"
echo "session_id: $session" >&2
nanobot agent --no-markdown -s "$session" -m "$HI_TASK" 2>&1 | python3 "$HI_HARNESS_DIR/report.py" "$session"
