# Oh My Pi

Oh My Pi (omp), headless over `omp -p --mode json`, on any provider through `$HOME/.omp/agent/models.yml`, where `apiKey` names the environment variable holding the credential.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/omp -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "omp"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "omp", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `omp/<provider>/<model>`. The folder is [`catalog/omp/`](../../../catalog/omp/).

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "Oh My Pi (omp) 18.1.13, headless `omp -p --mode json`; any provider through models.yml.",
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
      "release-assets.githubusercontent.com"
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
VERSION=18.1.13
case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
mkdir -p "$HI_TOOLS/bin"
curl -fsSL "https://github.com/can1357/oh-my-pi/releases/download/v$VERSION/omp-linux-$arch" -o "$HI_TOOLS/bin/omp"
chmod 755 "$HI_TOOLS/bin/omp"
"$HI_TOOLS/bin/omp" --version
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
mkdir -p "$HOME/.omp/agent"
cat > "$HOME/.omp/agent/models.yml" <<EOF
providers:
  hi:
    baseUrl: ${HI_PROVIDER_URL%/v1}
    apiKey: ANTHROPIC_API_KEY
    api: anthropic-messages
    models:
      - id: $HI_MODEL
EOF
turn() {
  local args=(-p --mode json --approval-mode yolo --model "hi/$HI_MODEL")
  [ -s "$HI_DIR/session" ] && args+=(--resume "$(cat "$HI_DIR/session")")
  omp "${args[@]}" "$1" </dev/null | tee "$HI_DIR/last.jsonl"
  local rc=${PIPESTATUS[0]}
  grep -o '"type":"session"[^}]*' "$HI_DIR/last.jsonl" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 > "$HI_DIR/session.new" && [ -s "$HI_DIR/session.new" ] && mv "$HI_DIR/session.new" "$HI_DIR/session"
  return $rc
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- The session id is read from the first turn's `session` event and kept in `$HI_DIR`; later turns pass `--resume`.
- Stdin is appended to the prompt, so the CLI runs with `</dev/null`.
- `api: anthropic-messages` here; `openai-completions` or `openai-responses` with a `/v1` base for the OpenAI shapes.
