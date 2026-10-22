# Kimi Code

Kimi Code, headless over `kimi -p --output-format stream-json`, on an Anthropic- or OpenAI-chat-shaped provider through the `KIMI_MODEL_*` variables.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/kimi-code -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "kimi-code"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "kimi-code", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `kimi-code/<provider>/<model>`. The folder is [`catalog/kimi-code/`](../../../catalog/kimi-code/).

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "Kimi Code 2.0.0, headless `kimi -p --output-format stream-json`; Anthropic- or OpenAI chat-shaped providers.",
  "defaults": {
    "provider": "deepseek",
    "model": "deepseek-chat"
  },
  "provider_env": {
    "key": "KIMI_MODEL_API_KEY",
    "url": "KIMI_MODEL_BASE_URL"
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
VERSION=2.0.0
case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/MoonshotAI/kimi-code/releases/download/%40moonshot-ai%2Fkimi-code%40$VERSION/kimi-code-linux-$arch.tar.gz" -o "$tmp/kimi.tgz"
mkdir "$tmp/x" && tar -xzf "$tmp/kimi.tgz" -C "$tmp/x"
bin=$(find "$tmp/x" -type f -name kimi -perm -u+x | head -n 1)
mkdir -p "$HI_TOOLS/bin" && install -m 755 "$bin" "$HI_TOOLS/bin/kimi"
"$HI_TOOLS/bin/kimi" --version
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
export KIMI_MODEL_NAME="$HI_MODEL" KIMI_MODEL_PROVIDER_TYPE=anthropic KIMI_MODEL_BASE_URL="${KIMI_MODEL_BASE_URL%/v1}"
export KIMI_DISABLE_TELEMETRY=1 KIMI_CODE_NO_AUTO_UPDATE=1
turn() {
  local args=(-p "$1" --output-format stream-json)
  [ -f "$HI_DIR/turned" ] && args+=(-c)
  touch "$HI_DIR/turned"
  kimi "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed from the GitHub release archive.
- `-c` continues the last session for this directory.
- `KIMI_MODEL_PROVIDER_TYPE=anthropic` with a base without `/v1`; `openai` with a `/v1` base for chat completions.
