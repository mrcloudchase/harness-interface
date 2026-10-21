# Add Kilo CLI

Kilo CLI, an OpenCode fork, headless over `kilo run --format json --auto`, configured the same way through `KILO_CONFIG_CONTENT`.

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
kilo/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "Kilo CLI 7.8.1 (an OpenCode fork), headless `kilo run --format json --auto`.",
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
VERSION=7.8.1
case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/Kilo-Org/kilocode/releases/download/v$VERSION/kilo-linux-$arch.tar.gz" -o "$tmp/kilo.tgz"
mkdir -p "$tmp/x" && tar -xzf "$tmp/kilo.tgz" -C "$tmp/x"
bin=$(find "$tmp/x" -type f -name kilo -perm -u+x | head -n 1)
dir=$(dirname "$bin")
rm -rf "$HI_TOOLS/kilo" && mkdir -p "$HI_TOOLS/bin" && cp -r "$dir" "$HI_TOOLS/kilo" && chmod -R a+rX "$HI_TOOLS/kilo"
printf '#!/bin/sh\nexec "%s/kilo/kilo" "$@"\n' "$HI_TOOLS" > "$HI_TOOLS/bin/kilo" && chmod 755 "$HI_TOOLS/bin/kilo"
"$HI_TOOLS/bin/kilo" --version
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
export PWD="$HI_WORKSPACE" KILO_DISABLE_MODELS_FETCH=1 KILO_DISABLE_AUTOUPDATE=1 KILO_TELEMETRY_LEVEL=off KILO_PERMISSION='{"*":"allow"}'
export KILO_CONFIG_CONTENT=$(cat <<EOF
{"autoupdate": false, "share": "disabled", "enabled_providers": ["anthropic"], "experimental": {"openTelemetry": false},
 "provider": {"anthropic": {"options": {"baseURL": "${HI_PROVIDER_URL%/v1}/v1", "apiKey": "{env:ANTHROPIC_API_KEY}"}, "models": {"$HI_MODEL": {}}}},
 "model": "anthropic/$HI_MODEL", "small_model": "anthropic/$HI_MODEL"}
EOF
)
turn() {
  local args=(run --format json --auto -m "anthropic/$HI_MODEL")
  [ -f "$HI_DIR/turned" ] && args+=(-c)
  touch "$HI_DIR/turned"
  kilo "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf kilo.tgz -C kilo .
curl -s -X PUT $HI/v1/harnesses/kilo -H "Authorization: Bearer $KEY" --data-binary @kilo.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "kilo", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Installed from the GitHub release archive (the binary and its helpers in one directory, wrapped on PATH).
- `-c` continues the last session in this directory; `KILO_PERMISSION='{"*":"allow"}'` answers every permission.
- The four `KILO_*` switches stop the model fetch, autoupdate and telemetry.
