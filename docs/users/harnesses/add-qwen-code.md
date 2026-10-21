# Add Qwen Code

Qwen Code, headless over `qwen -o stream-json`, on an OpenAI chat-shaped provider through `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `OPENAI_MODEL`.

## Verified

`scripts/live.py` against a running server, sandbox `node22`, provider `deepseek-openai`, model `deepseek-chat`:
**9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/node22 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"image": "node:22-bookworm-slim", "egress": []}'
curl -s -X PUT $HI/v1/providers/deepseek-openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/v1", "api": "openai-chat", "key": "sk-…"}'
```

## 2. The folder

```
qwen-code/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "Qwen Code 0.25.2, headless `qwen -o stream-json`; any OpenAI chat-shaped provider.",
  "defaults": {
    "sandbox": "node22",
    "provider": "deepseek-openai",
    "model": "deepseek-chat"
  },
  "provider_env": {
    "key": "OPENAI_API_KEY",
    "url": "OPENAI_BASE_URL"
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
VERSION=0.25.2
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@qwen-code/qwen-code@$VERSION"
"$HI_TOOLS/bin/qwen" --version
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
export OPENAI_MODEL="$HI_MODEL" QWEN_CODE_SUPPRESS_YOLO_WARNING=1 QWEN_CODE_MODELS_DEV=off QWEN_USAGE_STATISTICS_ENABLED=0
turn() {
  local args=(--approval-mode yolo --auth-type openai -m "$HI_MODEL" -o stream-json)
  if [ -f "$HI_DIR/turned" ]; then args+=(--resume "$(sid_uuid)"); else args+=(--session-id "$(sid_uuid)"); fi
  touch "$HI_DIR/turned"
  qwen "${args[@]}" "$1" </dev/null
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf qwen-code.tgz -C qwen-code .
curl -s -X PUT $HI/v1/harnesses/qwen-code -H "Authorization: Bearer $KEY" --data-binary @qwen-code.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "qwen-code", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- The session id is derived from the platform's session id as a UUID: `--session-id` on the first turn, `--resume` after.
- Stdin is read into the prompt, so the CLI is run with `</dev/null` and the prompt as an argument.
- `--auth-type openai` with a `/v1` base; `openai-responses` is also accepted for an OpenAI Responses provider.
