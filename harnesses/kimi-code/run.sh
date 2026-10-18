#!/usr/bin/env bash
# Kimi Code, headless: -p one prompt, --output-format stream-json one JSON object per line. In -p
# mode tools run under its "auto" policy without asking. A follow-up passes -S <session_id>.
# Set in harness.json:
#   KIMI_CODE_HOME: sessions, index and logs, so -S <id> resumes later
#   HOME: the CLI's home, inside the workspace's .home
#   KIMI_DISABLE_TELEMETRY, KIMI_CODE_NO_AUTO_UPDATE: no telemetry and no self-update; the sandbox
#     reaches only the provider
#   files AGENTS.md: the request's instructions, which kimi reads from its working directory
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
mkdir -p "$KIMI_CODE_HOME"
# kimi ignores ANTHROPIC_* in the shell; the KIMI_MODEL_* family defines an in-memory provider.
export KIMI_MODEL_PROVIDER_TYPE=anthropic KIMI_MODEL_BASE_URL="${HI_PROVIDER_URL%/}" \
  KIMI_MODEL_API_KEY="$HI_PROVIDER_KEY" KIMI_MODEL_NAME="${HI_MODEL:-deepseek-chat}"
kimi -p "$HI_TASK" --output-format stream-json ${HI_SESSION_ID:+-S "$HI_SESSION_ID"} \
  | python3 "$HI_HARNESS_DIR/report.py"
