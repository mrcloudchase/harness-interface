# pi

pi (earendil-works), headless over `pi -p --mode json`. pi reads no base-URL variable, so the folder writes `$HOME/.pi/agent/models.json` every turn with a custom provider pointing at the gateway and `apiKey: "$ANTHROPIC_API_KEY"`, which pi expands from the environment.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/pi -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "pi"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "pi", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `pi/<provider>/<model>`. The folder is `catalog/pi/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "pi 1.3.0 (earendil-works), headless `pi -p --mode json`; Anthropic- or OpenAI-shaped providers.",
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
VERSION=1.3.0
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund --no-update-notifier "@earendil-works/pi-coding-agent@$VERSION"
PI_OFFLINE=1 "$HI_TOOLS/bin/pi" --version
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
export PI_OFFLINE=1 PI_TELEMETRY=0 PI_SKIP_VERSION_CHECK=1
mkdir -p "$HOME/.pi/agent"
cat > "$HOME/.pi/agent/models.json" <<EOF
{"providers": {"anthropic": {"baseUrl": "${HI_PROVIDER_URL%/v1}", "apiKey": "\$ANTHROPIC_API_KEY"},
               "hi": {"baseUrl": "${HI_PROVIDER_URL%/v1}", "api": "anthropic-messages", "apiKey": "\$ANTHROPIC_API_KEY", "models": [{"id": "$HI_MODEL"}]}}}
EOF
turn() { pi -p --mode json --provider hi --model "$HI_MODEL" --session-id "$HI_SESSION" "$1"; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- The session id is the platform's own (`--session-id $HI_SESSION`), so every later turn resumes the same pi session from the same workspace.
- `api: anthropic-messages` in the custom provider; for an OpenAI-chat provider use `openai-completions` and a `/v1` base.
- `PI_OFFLINE=1` keeps pi from calling its catalog and version check.
