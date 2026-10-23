# MiniMax Code

MiniMax Code (`mcode`), headless over `mcode exec --output-format stream-json`, on an Anthropic-shaped provider through a config file the folder writes into `$HG_DIR` each turn.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/minimax-code -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "minimax-code"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "minimax-code", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `minimax-code/<provider>/<model>`. The folder is `catalog/minimax-code/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "MiniMax Code 0.5.4, headless `mcode exec --output-format stream-json`; Anthropic- or OpenAI-shaped providers.",
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
      "github.com",
      "objects.githubusercontent.com",
      "release-assets.githubusercontent.com",
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
VERSION=0.5.4
tmp=$(mktemp -d)
curl -fsSL "https://github.com/MiniMax-AI/minimax-code/releases/download/v$VERSION/minimax-code-$VERSION.tar.gz" -o "$tmp/mcode.tgz"
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund --include=optional "$tmp/mcode.tgz"
"$HG_TOOLS/bin/mcode" --version
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
mkdir -p "$HOME/.minimax"
cat > "$HG_DIR/mcode.yaml" <<EOF
defaultModel: custom_provider:hg/$HG_MODEL
permissionMode: "off"
dataContribution:
  enabled: false
custom_provider:
  hg:
    kind: custom
    enabled: true
    api: anthropic-messages
    options:
      baseURL: ${HG_PROVIDER_URL%/v1}
      authMode: api-key
      apiKey: $ANTHROPIC_API_KEY
    models:
      $HG_MODEL: {}
EOF
turn() {
  local args=(exec --output-format stream-json --permission off --cwd "$HG_WORKSPACE" --config "$HG_DIR/mcode.yaml")
  [ -f "$HG_DIR/turned" ] && args+=(--continue)
  touch "$HG_DIR/turned"
  mcode "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- The config names a custom provider with the gateway URL and the session token as its key, and lists the model under `models` (an unlisted model is refused).
- `--continue` resumes the latest session in the workspace.
- `permissionMode: "off"` runs tools without checks; the container is the boundary.
