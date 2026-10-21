# Add OpenCode

OpenCode, headless over `opencode run --format json`. The provider is passed inline in `OPENCODE_CONFIG_CONTENT`: the gateway's base URL with `/v1`, the key as `{env:ANTHROPIC_API_KEY}` and the model declared, so an id outside its catalog works.

## Verified

`scripts/live.py` against a running server, sandbox `full`, provider `deepseek`, model `deepseek-chat`:
**9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/full -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM node:22-bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip git curl ca-certificates ripgrep procps tmux && rm -rf /var/lib/apt/lists/*\n", "egress": []}'
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/anthropic", "api": "anthropic-messages", "key": "sk-…"}'
```

## 2. The folder

```
opencode/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "OpenCode 1.19.3, headless `opencode run --format json`; Anthropic-, Responses- or chat-shaped providers.",
  "defaults": {
    "sandbox": "full",
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
set -uo pipefail
prompt=$(cat)
cd "$HI_WORKSPACE"
sid_uuid() { local h=${HI_SESSION#sess_}; echo "${h:0:8}-${h:8:4}-${h:12:4}-${h:16:4}-${h:20:12}"; }
set -m   # job control: each turn runs in its own process group, so the steer signal reaches this script and not the CLI
run_wait() {   # run a turn and wait for it, re-waiting after a signal interrupts the wait; a stop is passed on to the turn
  "$@" </dev/null & local pid=$! rc
  trap 'kill -TERM -- "-$pid" 2>/dev/null' TERM
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

## 3. Upload and run

```bash
tar czf opencode.tgz -C opencode .
curl -s -X PUT $HI/v1/harnesses/opencode -H "Authorization: Bearer $KEY" --data-binary @opencode.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "opencode", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- `-c` on later turns continues the last session in this directory, and each platform session has its own directory, so continuation is reliable.
- `PWD` is exported because OpenCode takes its directory from it rather than from `getcwd()`.
- The `OPENCODE_DISABLE_*` switches stop model fetching, autoupdate, LSP downloads and the embedded web UI.
- For an OpenAI Responses provider use provider id `openai` and no `/v1` suffix; for a chat provider, a custom provider with `npm: @ai-sdk/openai-compatible`.
