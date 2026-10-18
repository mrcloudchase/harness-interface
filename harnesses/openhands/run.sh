#!/usr/bin/env bash
# OpenHands CLI, headless: --headless --json streams one event per line, --override-with-envs reads
# LLM_MODEL / LLM_API_KEY / LLM_BASE_URL instead of the saved settings, --always-approve skips
# confirmations. Its stdout mixes Rich status lines with the JSON events; the reporter keeps both.
# It reads AGENTS.md only as untrusted repository context, for coding style and conventions, so
# the request's instructions go ahead of the task instead, in the message it does follow.
# Set in harness.json:
#   HOME: conversations persist under $HOME/.openhands, so --resume works later
#   OPENHANDS_SUPPRESS_BANNER: no startup banner in the output
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
model="${HI_MODEL:-claude-sonnet-4-5}"
[[ "$model" == */* ]] || model="anthropic/$model"   # litellm wants the provider prefix
task="$(python3 -c '
import json, os
r = json.load(open(os.environ["HI_REQUEST"]))
print("\n\n".join(p for p in ((r.get("instructions") or "").strip(), r["task"]) if p))')"
export LLM_MODEL="$model" LLM_API_KEY="$HI_PROVIDER_KEY" LLM_BASE_URL="${HI_PROVIDER_URL%/}"
openhands --headless --json --override-with-envs --always-approve --exit-without-confirmation \
  ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} -t "$task" \
  | python3 "$HI_HARNESS_DIR/report.py"
