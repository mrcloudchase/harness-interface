# Claude Code

Claude Code, headless over `claude -p --output-format stream-json`, on any provider that speaks Anthropic Messages (Anthropic itself, DeepSeek's `/anthropic` endpoint, most aggregators). The conversation lives under `$HOME/.claude`, so `--continue` on later turns resumes it from the member's own home.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/claude-code -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "claude-code"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "claude-code", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `claude-code/<provider>/<model>`. The folder is `catalog/claude-code/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "Claude Code 2.1.305, headless over stream-json; any Anthropic-shaped provider.",
  "defaults": {
    "provider": "deepseek",
    "model": "deepseek-chat"
  },
  "provider_env": {
    "key": "ANTHROPIC_API_KEY",
    "url": "ANTHROPIC_BASE_URL"
  },
  "interrupt": "SIGUSR1",
  "install": {
    "egress": [
      "registry.npmjs.org"
    ],
    "timeout_s": 1200
  },
  "run": {
    "egress": [],
    "timeout_s": 1800,
    "stop_timeout_s": 20
  }
}
```

`install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
VERSION=2.1.305
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@$VERSION"
"$HG_TOOLS/bin/claude" --version
```

`request.sh`:

```bash
#!/usr/bin/env bash
# request.sh: one turn. The prompt is on stdin; stdout is relayed live and kept for response.sh.
# A steer arrives as $HG_DIR/interrupt plus the package's signal, delivered to this script alone,
# so the trap below runs the steer as the next turn once the current one ends.
set -uo pipefail
prompt=$(cat)
sid_uuid() { local h=${HG_SESSION#sess_}; echo "${h:0:8}-${h:8:4}-${h:12:4}-${h:16:4}-${h:20:12}"; }
run_wait() {   # run a turn and wait for it, re-waiting after a signal interrupts the wait
  "$@" </dev/null & local pid=$! rc
  while :; do wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null || break; done
  return $rc
}
steer=""
trap 'steer=$(cat "$HG_DIR/interrupt" 2>/dev/null || true)' USR1
export IS_SANDBOX=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
export ANTHROPIC_DEFAULT_HAIKU_MODEL="$HG_MODEL" ANTHROPIC_SMALL_FAST_MODEL="$HG_MODEL"
turn() {
  local args=(-p "$1" --output-format stream-json --verbose --dangerously-skip-permissions --model "$HG_MODEL")
  [ -n "${HG_INSTRUCTIONS:-}" ] && args+=(--append-system-prompt "$HG_INSTRUCTIONS")
  [ "$HG_TURN" -gt 1 ] || [ -f "$HG_DIR/turned" ] && args+=(--continue)
  touch "$HG_DIR/turned"
  claude "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

`seeds/org/.claude/CLAUDE.md`:

```
Answer in one short sentence unless asked for code.
```

## Notes

- `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` come from `provider_env`: the session token and the gateway URL. Claude appends `/v1/messages` itself, so the URL is passed without `/v1`.
- `IS_SANDBOX=1` lets `--dangerously-skip-permissions` run as the sandbox user; `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` keeps it to the provider, which is all the door allows anyway.
- The two `ANTHROPIC_*_MODEL` variables make its background and fast calls use the same model, so a non-Anthropic provider never sees a Claude model id.
- `seeds/org/.claude/CLAUDE.md` is where the org's standing instructions go; `HG_INSTRUCTIONS` becomes `--append-system-prompt`.
- A steer is delivered after the running turn ends, as the next `--continue` message.
