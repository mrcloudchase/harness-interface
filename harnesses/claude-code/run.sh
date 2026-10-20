#!/usr/bin/env bash
# Maps HI_* onto Claude Code's own settings, then execs the adapter. The key's value is never in the
# environment: home/.claude/settings.json sets apiKeyHelper to read $HI_PROVIDER_KEY_FILE, which
# claude runs itself, so the key (or, under the gateway, the session's token) stays in its memory.
set -euo pipefail
cd "$HI_WORKSPACE"
export PYTHONDONTWRITEBYTECODE=1                     # nothing written into the folder or the workspace
export IS_SANDBOX=1                                  # --dangerously-skip-permissions is allowed as root (local runs)
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1    # no telemetry, error reports or updater: the provider only
export CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1        # a backgrounded Bash would outlive a stop
# Auto memory stays on: claude files what it chooses to remember under .claude/projects/*/memory/,
# which harness.json reports back. CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 would turn it off.
if [ -n "${HI_PROVIDER_URL:-}" ]; then
  export ANTHROPIC_BASE_URL="$HI_PROVIDER_URL"       # the SDK's base, no /v1: claude appends /v1/messages
fi
if [ -n "${HI_MODEL:-}" ]; then                      # background and "fast" calls use the same model, so
  export ANTHROPIC_DEFAULT_HAIKU_MODEL="$HI_MODEL"   # another provider never sees a claude-haiku id
  export ANTHROPIC_SMALL_FAST_MODEL="$HI_MODEL"
fi
exec python3 -u "$HI_HARNESS_DIR/adapter.py"
