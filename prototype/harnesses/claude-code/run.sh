#!/usr/bin/env bash
# Maps HI_* onto Claude Code's settings, then execs the adapter.
# The key never goes into the environment: home/.claude/settings.json sets
# apiKeyHelper = `cat "$HI_PROVIDER_KEY_FILE"`, which claude runs to get it.
set -euo pipefail
cd "$HI_WORKSPACE"
export IS_SANDBOX=1                                  # --dangerously-skip-permissions as root (local runs)
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1    # no telemetry, error reports, updater: provider only
export CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1        # a backgrounded Bash would outlive an interrupt
if [ -n "${HI_PROVIDER_URL:-}" ]; then
  url="${HI_PROVIDER_URL%/}"
  export ANTHROPIC_BASE_URL="${url%/v1}"             # claude appends /v1/messages itself
fi
if [ -n "${HI_MODEL:-}" ]; then                      # background/"fast" calls use the same model, so a
  export ANTHROPIC_DEFAULT_HAIKU_MODEL="$HI_MODEL"   # non-Anthropic provider never sees a claude-haiku id
  export ANTHROPIC_SMALL_FAST_MODEL="$HI_MODEL"
fi
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
