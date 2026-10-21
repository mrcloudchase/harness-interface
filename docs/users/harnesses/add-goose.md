# Add goose

goose, headless over `goose run`, on an Anthropic-shaped provider through `GOOSE_PROVIDER`, `GOOSE_MODEL` and `ANTHROPIC_HOST`.

## Verified

`scripts/live.py` against a running server, sandbox `full`, provider `deepseek`, model `deepseek-chat`:
**9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/full -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM node:22-bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip git curl ca-certificates ripgrep procps tmux && rm -rf /var/lib/apt/lists/*\n", "egress": []}'
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/anthropic", "api": "anthropic-messages", "key": "sk-…"}'
```

## 2. The folder

```
goose/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "goose 1.50.0, headless `goose run`; Anthropic- or OpenAI-shaped providers.",
  "defaults": {
    "sandbox": "full",
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
    "timeout_s": 1800,
    "stop_timeout_s": 20
  }
}
```

`install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
VERSION=1.50.0
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/aaif-goose/goose/releases/download/v$VERSION/goose-$arch-unknown-linux-gnu.tar.gz" -o "$tmp/goose.tgz"
tar -xzf "$tmp/goose.tgz" -C "$tmp"
mkdir -p "$HI_TOOLS/bin" && install -m 755 "$tmp/goose" "$HI_TOOLS/bin/goose"
"$HI_TOOLS/bin/goose" --version
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
export GOOSE_PROVIDER=anthropic GOOSE_MODEL="$HI_MODEL" ANTHROPIC_HOST="${HI_PROVIDER_URL%/v1}" GOOSE_DISABLE_SESSION_NAMING=1 RUST_BACKTRACE=0
export GOOSE_MODE=auto
turn() {
  local args=(run -t "$1" --output-format stream-json -n "$HI_SESSION")
  [ -f "$HI_DIR/turned" ] && args+=(-r)
  touch "$HI_DIR/turned"
  goose "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf goose.tgz -C goose .
curl -s -X PUT $HI/v1/harnesses/goose -H "Authorization: Bearer $KEY" --data-binary @goose.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "goose", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Sessions are named after the platform session (`-n $HI_SESSION`) and resumed with `-r`.
- `ANTHROPIC_HOST` is the base without `/v1`; for an OpenAI provider set `GOOSE_PROVIDER=openai` and `OPENAI_BASE_URL` with `/v1`.
- `GOOSE_MODE=auto` approves every tool call; `GOOSE_DISABLE_SESSION_NAMING=1` saves a model call per turn.
- Its stream-json output starts with a three-line text banner; a program reading it should skip lines that are not JSON.
- Assistant text arrives token-chunked across `message` events; join the `text` fields to read it.
