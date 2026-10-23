# MiMo Code

MiMo Code, an OpenCode-style CLI, headless over `mimo run --format json`, on an Anthropic-shaped provider through `MIMOCODE_CONFIG_CONTENT`.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/mimo -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "mimo"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "mimo", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `mimo/<provider>/<model>`. The folder is `catalog/mimo/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "MiMo Code 0.1.15, headless `mimo run --format json`; any Anthropic-shaped provider.",
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
    "timeout_s": 1500
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
VERSION=0.1.15
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@mimo-ai/cli@$VERSION"
HOME=$(mktemp -d) "$HI_TOOLS/bin/mimo" --version
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

## Notes

- `-c` continues the last session in this directory.
- The `MIMOCODE_*` switches stop the model fetch, autoupdate and analytics.
- Its first start migrates a local database, which can take a while; later turns are quick.
