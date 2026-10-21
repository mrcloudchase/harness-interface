# Add MiniMax Code

MiniMax Code (`mcode`), headless over `mcode exec --output-format stream-json`, on an Anthropic-shaped provider through a config file the folder writes into `$HI_DIR` each turn.

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
minimax-code/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "MiniMax Code 0.5.4, headless `mcode exec --output-format stream-json`; Anthropic- or OpenAI-shaped providers.",
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
      "github.com",
      "objects.githubusercontent.com",
      "release-assets.githubusercontent.com",
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
VERSION=0.5.4
tmp=$(mktemp -d)
curl -fsSL "https://github.com/MiniMax-AI/minimax-code/releases/download/v$VERSION/minimax-code-$VERSION.tar.gz" -o "$tmp/mcode.tgz"
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund --include=optional "$tmp/mcode.tgz"
"$HI_TOOLS/bin/mcode" --version
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
mkdir -p "$HOME/.minimax"
cat > "$HI_DIR/mcode.yaml" <<EOF
defaultModel: custom_provider:hi/$HI_MODEL
permissionMode: "off"
dataContribution:
  enabled: false
custom_provider:
  hi:
    kind: custom
    enabled: true
    api: anthropic-messages
    options:
      baseURL: ${HI_PROVIDER_URL%/v1}
      authMode: api-key
      apiKey: $ANTHROPIC_API_KEY
    models:
      $HI_MODEL: {}
EOF
turn() {
  local args=(exec --output-format stream-json --permission off --cwd "$HI_WORKSPACE" --config "$HI_DIR/mcode.yaml")
  [ -f "$HI_DIR/turned" ] && args+=(--continue)
  touch "$HI_DIR/turned"
  mcode "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf minimax-code.tgz -C minimax-code .
curl -s -X PUT $HI/v1/harnesses/minimax-code -H "Authorization: Bearer $KEY" --data-binary @minimax-code.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "minimax-code", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- The config names a custom provider with the gateway URL and the session token as its key, and lists the model under `models` (an unlisted model is refused).
- `--continue` resumes the latest session in the workspace.
- `permissionMode: "off"` runs tools without checks; the container is the boundary.
