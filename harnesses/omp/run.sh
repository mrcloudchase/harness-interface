#!/usr/bin/env bash
# omp, headless: -p one prompt, --mode json one event per line, --approval-mode yolo no prompts.
# A follow-up reopens the session id that the first turn's `session` event reported. Its stdin is
# empty: omp appends stdin to the prompt, and the server's stdin carries the request JSON.
# Set in harness.json:
#   HOME: sessions and agent.db land under $HOME/.omp/agent, so --resume works later
#   files AGENTS.md: the request's instructions, which omp reads from its working directory
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
export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
# omp sends model calls through PI_PROXY, not HTTPS_PROXY; in the sandbox the egress door is the only way out.
if [ -n "${HTTPS_PROXY:-}" ]; then export PI_PROXY="$HTTPS_PROXY"; fi
# omp wants a provider-qualified model; the harness picks a default when none is given.
omp -p --mode json --approval-mode yolo --model "anthropic/${HI_MODEL:-claude-sonnet-4-5}" \
  ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} "$HI_TASK" </dev/null \
  | python3 "$HI_HARNESS_DIR/report.py"
