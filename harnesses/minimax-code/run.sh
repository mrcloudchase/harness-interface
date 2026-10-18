#!/usr/bin/env bash
# MiniMax Code, headless. `provider add --use` registers the BYOK endpoint under $HOME/.minimax and
# selects it (without a selected provider, exec demands a MiniMax login); re-adding the same name
# replaces it. The key is read from the named env var at add time and stored in config.yaml, which
# lives under .home/, never listed or committed. A follow-up passes --session <id>.
# Set in harness.json:
#   HOME: config.yaml (provider) and sessions live under $HOME/.minimax, so --session works later
#   files AGENTS.md: the request's instructions, which it reads from its working directory
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
mkdir -p "$HOME"
model="${HI_MODEL:-deepseek-chat}"
mcode provider add --name hi --base-url "${HI_PROVIDER_URL%/}" --api-format anthropic-messages \
  --model "$model" --api-key-env HI_PROVIDER_KEY --use >&2
mcode exec --model "custom_provider:hi/$model" --output-format stream-json --permission off \
  --cwd "$HI_WORKSPACE" ${HI_SESSION_ID:+--session "$HI_SESSION_ID"} "$HI_TASK" \
  | python3 "$HI_HARNESS_DIR/report.py"
