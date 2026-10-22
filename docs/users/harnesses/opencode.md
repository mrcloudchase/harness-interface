# OpenCode

OpenCode, headless over `opencode run --format json`. The provider is passed inline in `OPENCODE_CONFIG_CONTENT`: the gateway's base URL with `/v1`, the key as `{env:ANTHROPIC_API_KEY}` and the model declared, so an id outside its catalog works.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/opencode -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "opencode"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "opencode", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `opencode/<provider>/<model>`. The folder is [`catalog/opencode/`](../../../catalog/opencode/).

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "OpenCode 1.19.3, headless `opencode run --format json`; Anthropic-, Responses- or chat-shaped providers.",
  "defaults": {
    "provider": "deepseek",
    "model": "deepseek-chat"
  },
  "provider_env": {
    "key": "ANTHROPIC_API_KEY",
    "url": ""
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
VERSION=1.19.3
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "opencode-ai@$VERSION"
rm -rf "$HI_TOOLS/lib/node_modules/opencode-ai/node_modules"
"$HI_TOOLS/bin/opencode" --version
```

`request.sh`:

```bash
#!/usr/bin/env bash
# request.sh: one turn. The prompt is on stdin; stdout is relayed live and kept for response.sh.
# A steer arrives as $HI_DIR/interrupt plus the package's signal, delivered to this script alone,
# so the trap below runs the steer as the next turn once the current one ends.
set -uo pipefail
prompt=$(cat)
sid_uuid() { local h=${HI_SESSION#sess_}; echo "${h:0:8}-${h:8:4}-${h:12:4}-${h:16:4}-${h:20:12}"; }
run_wait() {   # run a turn and wait for it, re-waiting after a signal interrupts the wait
  "$@" </dev/null & local pid=$! rc
  while :; do wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null || break; done
  return $rc
}
steer=""
trap 'steer=$(cat "$HI_DIR/interrupt" 2>/dev/null || true)' USR1
export PWD="$HI_WORKSPACE" OPENCODE_DISABLE_MODELS_FETCH=1 OPENCODE_DISABLE_AUTOUPDATE=1 OPENCODE_DISABLE_LSP_DOWNLOAD=1
export OPENCODE_DISABLE_DEFAULT_PLUGINS=1 OPENCODE_DISABLE_CLAUDE_CODE=1 npm_config_offline=true
export OPENCODE_CONFIG_CONTENT=$(cat <<EOF
{"autoupdate": false, "share": "disabled", "snapshot": false, "lsp": false, "formatter": false,
 "permission": {"*": "allow", "question": "deny"}, "enabled_providers": ["anthropic"],
 "provider": {"anthropic": {"options": {"baseURL": "${HI_PROVIDER_URL%/v1}/v1", "apiKey": "{env:ANTHROPIC_API_KEY}"}, "models": {"$HI_MODEL": {}}}},
 "model": "anthropic/$HI_MODEL", "small_model": "anthropic/$HI_MODEL"}
EOF
)
turn() {
  local args=(run --format json -m "anthropic/$HI_MODEL")
  [ -f "$HI_DIR/turned" ] && args+=(-c)
  touch "$HI_DIR/turned"
  opencode "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- `-c` on later turns continues the last session in this directory, and each platform session has its own directory, so continuation is reliable.
- `PWD` is exported because OpenCode takes its directory from it rather than from `getcwd()`.
- The `OPENCODE_DISABLE_*` switches stop model fetching, autoupdate, LSP downloads and the embedded web UI.
- For an OpenAI Responses provider use provider id `openai` and no `/v1` suffix; for a chat provider, a custom provider with `npm: @ai-sdk/openai-compatible`.
