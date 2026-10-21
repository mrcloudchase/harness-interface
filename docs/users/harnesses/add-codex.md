# Add Codex

OpenAI's Codex CLI, headless over `codex exec --json`, on any provider that speaks the OpenAI Responses API. The thread id from the first turn is kept in `$HI_DIR` and later turns run `codex exec resume <id>`.

## Verified

`scripts/live.py` against a running server, sandbox `node22`, provider `openai-responses`, model `gpt-5.4-mini`:
**0 of 9** checks passed ().

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/node22 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"image": "node:22-bookworm-slim", "egress": []}'
curl -s -X PUT $HI/v1/providers/openai-responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.openai.com/v1", "api": "openai-responses", "key": "sk-…"}'
```

## 2. The folder

```
codex/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "OpenAI Codex CLI 0.163.0, headless over `codex exec --json`; any Responses-shaped provider.",
  "defaults": {
    "sandbox": "node22",
    "provider": "openai-responses",
    "model": "gpt-5.4-mini"
  },
  "provider_env": {
    "key": "OPENAI_API_KEY",
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
VERSION=0.163.0
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@openai/codex@$VERSION"
"$HI_TOOLS/bin/codex" --version
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
export CODEX_HOME="$HOME/.codex"
mkdir -p "$CODEX_HOME"
cat > "$CODEX_HOME/config.toml" <<EOF
model_provider = "hi"
model = "$HI_MODEL"
approval_policy = "never"
sandbox_mode = "danger-full-access"
check_for_update_on_startup = false
[model_providers.hi]
name = "hi"
base_url = "${HI_PROVIDER_URL%/}"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
[features]
plugins = false
api_key_model_discovery = false
unbounded_connection_retries = false
[analytics]
enabled = false
EOF
turn() {
  if [ -s "$HI_DIR/thread" ]; then
    codex exec resume --json --skip-git-repo-check "$(cat "$HI_DIR/thread")" "$1"
  else
    codex exec --json --skip-git-repo-check -m "$HI_MODEL" "$1" | tee "$HI_DIR/last.jsonl"
    local rc=${PIPESTATUS[0]}
    grep -o '"thread_id":"[^"]*"' "$HI_DIR/last.jsonl" | head -1 | cut -d'"' -f4 > "$HI_DIR/thread"
    return $rc
  fi
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf codex.tgz -C codex .
curl -s -X PUT $HI/v1/harnesses/codex -H "Authorization: Bearer $KEY" --data-binary @codex.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "codex", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Codex reads its provider from `$CODEX_HOME/config.toml`, written every turn: `model_providers.hi` with the gateway's `/v1` base and `env_key = "OPENAI_API_KEY"`, which `provider_env` sets to the session token.
- `sandbox_mode = "danger-full-access"` and `--skip-git-repo-check`: the container is the sandbox and the workspace need not be a git repository.
- The three `features` switches stop Codex cloning its plugin repository and discovering models over the network, both of which the door would refuse anyway.
- The request's model path (`node22/codex/openai-responses/<model>`) picks the model; `gpt-5.4-mini` is the default here.
