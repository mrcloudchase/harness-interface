#!/usr/bin/env bash
# MiMo Code, headless: `mimo run --format json` prints one event per line. A follow-up continues
# the session id from the first turn with -s. The config is passed inline, so no file is written.
# Set in harness.json:
#   HOME: sessions live in $HOME/.local/share/mimocode/mimocode.db, so -s resumes later
#   MIMOCODE_DISABLE_AUTOUPDATE: no self-update; the sandbox reaches only the provider
#   files AGENTS.md: the request's instructions, which mimo reads from its working directory
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
base="${HI_PROVIDER_URL%/}"; base="${base%/v1}/v1"   # mimo appends /messages, so the base carries /v1
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
export MIMOCODE_CONFIG_CONTENT="{\"provider\":{\"anthropic\":{\"options\":{\"baseURL\":\"${base}\"}}}}"
# Without --model mimo falls back to the last used or its own first model, so the harness names one,
# from mimo's bundled catalog: the sandbox cannot fetch a newer one.
mimo run --format json --dangerously-skip-permissions -m "anthropic/${HI_MODEL:-claude-sonnet-4-5}" \
  ${HI_SESSION_ID:+-s "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
