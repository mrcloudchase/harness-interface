# Add jcode

jcode, headless over `jcode run --ndjson`, on an Anthropic-shaped provider through `ANTHROPIC_BASE_URL` (with `/v1`) and `ANTHROPIC_API_KEY`.

## Verified

`scripts/live.py` against a running server, sandbox `full`, provider `deepseek`, model `(the provider default)`:
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
jcode/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "jcode 0.90.0, headless `jcode run --ndjson`; an Anthropic-shaped provider.",
  "defaults": {
    "sandbox": "full",
    "provider": "deepseek",
    "model": ""
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
VERSION=0.90.0
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/1jehuang/jcode/releases/download/v$VERSION/jcode-linux-$arch.tar.gz" -o "$tmp/jcode.tgz"
tar -xzf "$tmp/jcode.tgz" -C "$tmp"
rm -rf "$HI_TOOLS/jcode" && mkdir -p "$HI_TOOLS/jcode" "$HI_TOOLS/bin"
if [ -f "$tmp/jcode-linux-$arch.bin" ]; then
  install -m 755 "$tmp/jcode-linux-$arch" "$tmp/jcode-linux-$arch.bin" "$HI_TOOLS/jcode/"
  ln -sf "$HI_TOOLS/jcode/jcode-linux-$arch" "$HI_TOOLS/bin/jcode"
else
  install -m 755 "$tmp/jcode-linux-$arch" "$HI_TOOLS/bin/jcode"
fi
"$HI_TOOLS/bin/jcode" --version
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
export ANTHROPIC_BASE_URL="${HI_PROVIDER_URL%/v1}/v1" JCODE_NO_TELEMETRY=1 JCODE_RUN_AUTO_POKE=0 JCODE_RUNTIME_DIR=/tmp/jcode-rt
turn() {
  local args=(run --ndjson --no-update -p anthropic-api)
  [ -s "$HI_DIR/session" ] && args+=(--resume "$(cat "$HI_DIR/session")")
  [ -n "$HI_MODEL" ] && [ ! -s "$HI_DIR/session" ] && args+=(-m "$HI_MODEL")
  jcode "${args[@]}" "$1" | tee "$HI_DIR/last.jsonl"
  local rc=${PIPESTATUS[0]}
  grep -o '"session_id":"[^"]*"' "$HI_DIR/last.jsonl" | head -1 | cut -d'"' -f4 > "$HI_DIR/session.new" && [ -s "$HI_DIR/session.new" ] && mv "$HI_DIR/session.new" "$HI_DIR/session"
  return $rc
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf jcode.tgz -C jcode .
curl -s -X PUT $HI/v1/harnesses/jcode -H "Authorization: Bearer $KEY" --data-binary @jcode.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "jcode", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Installed from the GitHub release archive, which holds a launcher and a `.bin` beside it.
- The session id is read from the first line of its output and kept in `$HI_DIR`; later turns pass `--resume`.
- jcode only accepts model ids from its own catalog, so with a non-Anthropic provider the folder sends no `-m`, and the provider maps jcode's default id to its own model. Name a catalog id in the request's model path when the provider serves one.
- It also tries to fetch a model catalog from Anthropic directly; the door refuses that and the run is unaffected.
