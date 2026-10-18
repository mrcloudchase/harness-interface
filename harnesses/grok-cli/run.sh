#!/usr/bin/env bash
# Grok Build, headless: -p one prompt, --output-format streaming-json (ACP updates, one per line).
# The provider is a custom model written into config.toml on every turn; the key stays in the
# environment (env_key), never in the file. A follow-up passes --resume <session_id>.
# Set in harness.json:
#   HOME: config.toml and sessions live under $HOME/.grok, so --resume works later
#   GROK_FOLDER_TRUST: off, so a headless run reads the workspace's AGENTS.md; trusting a folder
#     is a prompt nobody can answer here, and the sandbox is the boundary
#   GROK_AUTO_UPDATE: off; the sandbox reaches only the provider
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
mkdir -p "$HOME/.grok"
cat > "$HOME/.grok/config.toml" <<CFG
[models]
default = "hi"
[model.hi]
model = "${HI_MODEL:-deepseek-chat}"
base_url = "${HI_PROVIDER_URL%/}"
env_key = "HI_PROVIDER_KEY"
api_backend = "chat_completions"
context_window = 128000
CFG
grok -p "$HI_TASK" -m hi --output-format streaming-json --permission-mode bypassPermissions \
  ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} | python3 "$HI_HARNESS_DIR/report.py"
