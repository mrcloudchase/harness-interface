# Add MiMo Code

MiMo Code, an OpenCode-style CLI, headless over `mimo run --format json`, on an Anthropic-shaped provider through `MIMOCODE_CONFIG_CONTENT`.

## Verified

`scripts/live.py` against a running server, sandbox `node22`, provider `deepseek`, model `deepseek-chat`:
**9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/node22 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"image": "node:22-bookworm-slim", "egress": []}'
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/anthropic", "api": "anthropic-messages", "key": "sk-…"}'
```

## 2. The folder

```
mimo/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "MiMo Code 0.1.15, headless `mimo run --format json`; any Anthropic-shaped provider.",
  "defaults": {
    "sandbox": "node22",
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
    "timeout_s": 1500
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
VERSION=0.1.15
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@mimo-ai/cli@$VERSION"
HOME=$(mktemp -d) "$HI_TOOLS/bin/mimo" --version
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
export MIMOCODE_DISABLE_AUTOUPDATE=1 MIMOCODE_DISABLE_MODELS_FETCH=1 MIMOCODE_ENABLE_ANALYSIS=0
export MIMOCODE_CONFIG_CONTENT=$(cat <<EOF
{"provider": {"anthropic": {"options": {"baseURL": "${HI_PROVIDER_URL%/v1}/v1"}, "models": {"$HI_MODEL": {}}}}, "model": "anthropic/$HI_MODEL"}
EOF
)
turn() {
  local args=(run --format json -m "anthropic/$HI_MODEL")
  [ -f "$HI_DIR/turned" ] && args+=(-c)
  touch "$HI_DIR/turned"
  mimo "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf mimo.tgz -C mimo .
curl -s -X PUT $HI/v1/harnesses/mimo -H "Authorization: Bearer $KEY" --data-binary @mimo.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "mimo", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- `-c` continues the last session in this directory.
- The `MIMOCODE_*` switches stop the model fetch, autoupdate and analytics.
- Its first start migrates a local database, which can take a while; later turns are quick.
