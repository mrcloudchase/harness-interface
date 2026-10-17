#!/usr/bin/env bash
# Gemini CLI, headless. --resume takes "latest" or an index, so a follow-up resumes the latest
# session in this workspace's HOME, which is this conversation's.
# Set in harness.json:
#   HOME: sessions under $HOME/.gemini, so --resume works later
set -euo pipefail
# Gemini CLI needs the auth type chosen in its settings, and ignores --yolo in a folder it does
# not trust, so both are set here.
mkdir -p "$HOME/.gemini"
printf '%s' '{"security":{"auth":{"selectedType":"gemini-api-key"},"folderTrust":{"enabled":false}}}' > "$HOME/.gemini/settings.json"
export GEMINI_API_KEY="$HI_PROVIDER_KEY" GOOGLE_GEMINI_BASE_URL="${HI_PROVIDER_URL%/}"
# stdin is empty: gemini appends stdin to the prompt, and the server's stdin carries the request JSON.
gemini -p "$HI_TASK" --output-format stream-json --yolo ${HI_MODEL:+-m "$HI_MODEL"} \
  ${HI_SESSION_ID:+--resume latest} </dev/null | python3 "$HI_HARNESS_DIR/report.py"
