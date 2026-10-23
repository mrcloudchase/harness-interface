# Codex

OpenAI's Codex CLI, headless over `codex exec --json`, on any provider that speaks the OpenAI Responses API. The thread id from the first turn is kept in `$HG_DIR` and later turns run `codex exec resume <id>`.

## Verified

`scripts/live.py` against a running platform, provider `openai-responses`, model `gpt-5.4-mini`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HG/v1/providers/openai-responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/codex -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "codex"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "codex", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `openai-responses` and its default model `gpt-5.4-mini`; name another with `codex/<provider>/<model>`. The folder is `catalog/codex/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "OpenAI Codex CLI 0.163.0, headless over `codex exec --json`; any Responses-shaped provider.",
  "defaults": {
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
VERSION=0.163.0
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "@openai/codex@$VERSION"
"$HG_TOOLS/bin/codex" --version
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
export CODEX_HOME="$HOME/.codex"
mkdir -p "$CODEX_HOME"
cat > "$CODEX_HOME/config.toml" <<EOF
model_provider = "hi"
model = "$HG_MODEL"
approval_policy = "never"
sandbox_mode = "danger-full-access"
check_for_update_on_startup = false
[model_providers.hi]
name = "hi"
base_url = "${HG_PROVIDER_URL%/}"
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
  if [ -s "$HG_DIR/thread" ]; then
    codex exec resume --json --skip-git-repo-check "$(cat "$HG_DIR/thread")" "$1"
  else
    codex exec --json --skip-git-repo-check -m "$HG_MODEL" "$1" | tee "$HG_DIR/last.jsonl"
    local rc=${PIPESTATUS[0]}
    grep -o '"thread_id":"[^"]*"' "$HG_DIR/last.jsonl" | head -1 | cut -d'"' -f4 > "$HG_DIR/thread"
    return $rc
  fi
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Codex reads its provider from `$CODEX_HOME/config.toml`, written every turn: `model_providers.hi` with the gateway's `/v1` base and `env_key = "OPENAI_API_KEY"`, which `provider_env` sets to the session token.
- `sandbox_mode = "danger-full-access"` and `--skip-git-repo-check`: the container is the sandbox and the workspace need not be a git repository.
- The three `features` switches stop Codex cloning its plugin repository and discovering models over the network, both of which the door would refuse anyway.
- The request's model path (`node22/codex/openai-responses/<model>`) picks the model; `gpt-5.4-mini` is the default here.
