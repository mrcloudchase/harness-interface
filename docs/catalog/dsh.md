# DeepSeek Harness

The DeepSeek Harness (`dsh`), headless over `dsh --profile headless --json`, on DeepSeek's Anthropic-shaped endpoint through `DEEPSEEK_BASE_URL` and `DEEPSEEK_API_KEY`.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/dsh -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "dsh"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "dsh", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `dsh/<provider>/<model>`. The folder is `catalog/dsh/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "DeepSeek Harness (dsh) 0.2.0-rc.2, headless `dsh --profile headless --json`; DeepSeek's Anthropic-shaped endpoint.",
  "defaults": {
    "provider": "deepseek",
    "model": "deepseek-chat"
  },
  "provider_env": {
    "key": "DEEPSEEK_API_KEY",
    "url": "DEEPSEEK_BASE_URL"
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
VERSION=0.2.0-rc.2
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@deepseek-ai/dsh@$VERSION"
"$HI_TOOLS/bin/dsh" --version </dev/null
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
export DEEPSEEK_BASE_URL="${DEEPSEEK_BASE_URL%/v1}" DSH_TELEMETRY_DISABLED=1 DSH_PERMISSION_MODE=danger-full-access
cat > "$HI_DIR/patch.yml" <<EOF
- id: agent-default-model
  config: {provider: deepseek-official, model: $HI_MODEL}
EOF
turn() {
  local args=(--profile headless --patch "$HI_DIR/patch.yml" --json)
  [ -s "$HI_DIR/session" ] && args+=(--session-id "$(cat "$HI_DIR/session")")
  dsh "${args[@]}" "$1" </dev/null | tee "$HI_DIR/last.jsonl"
  local rc=${PIPESTATUS[0]}
  grep -o '"sessionId":"[^"]*"' "$HI_DIR/last.jsonl" | head -1 | cut -d'"' -f4 > "$HI_DIR/session.new" && [ -s "$HI_DIR/session.new" ] && mv "$HI_DIR/session.new" "$HI_DIR/session"
  return $rc
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- The model is set by a config patch (`--patch`) the folder writes each turn; dsh has no model flag.
- The session id is read from its `session` event and kept in `$HI_DIR`; later turns pass `--session-id`.
- `DSH_PERMISSION_MODE=danger-full-access` runs tools without approval prompts; stdin is closed with `</dev/null` because dsh reads it when the task is omitted.
