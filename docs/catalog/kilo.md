# Kilo CLI

Kilo CLI, an OpenCode fork, headless over `kilo run --format json --auto`, configured the same way through `KILO_CONFIG_CONTENT`.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/kilo -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "kilo"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "kilo", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `kilo/<provider>/<model>`. The folder is `catalog/kilo/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "Kilo CLI 7.8.1 (an OpenCode fork), headless `kilo run --format json --auto`.",
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
VERSION=7.8.1
case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/Kilo-Org/kilocode/releases/download/v$VERSION/kilo-linux-$arch.tar.gz" -o "$tmp/kilo.tgz"
mkdir -p "$tmp/x" && tar -xzf "$tmp/kilo.tgz" -C "$tmp/x"
bin=$(find "$tmp/x" -type f -name kilo -perm -u+x | head -n 1)
dir=$(dirname "$bin")
rm -rf "$HG_TOOLS/kilo" && mkdir -p "$HG_TOOLS/bin" && cp -r "$dir" "$HG_TOOLS/kilo" && chmod -R a+rX "$HG_TOOLS/kilo"
printf '#!/bin/sh\nexec "%s/kilo/kilo" "$@"\n' "$HG_TOOLS" > "$HG_TOOLS/bin/kilo" && chmod 755 "$HG_TOOLS/bin/kilo"
"$HG_TOOLS/bin/kilo" --version
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
export PWD="$HG_WORKSPACE" KILO_DISABLE_MODELS_FETCH=1 KILO_DISABLE_AUTOUPDATE=1 KILO_TELEMETRY_LEVEL=off KILO_PERMISSION='{"*":"allow"}'
export KILO_CONFIG_CONTENT=$(cat <<EOF
{"autoupdate": false, "share": "disabled", "enabled_providers": ["anthropic"], "experimental": {"openTelemetry": false},
 "provider": {"anthropic": {"options": {"baseURL": "${HG_PROVIDER_URL%/v1}/v1", "apiKey": "{env:ANTHROPIC_API_KEY}"}, "models": {"$HG_MODEL": {}}}},
 "model": "anthropic/$HG_MODEL", "small_model": "anthropic/$HG_MODEL"}
EOF
)
turn() {
  local args=(run --format json --auto -m "anthropic/$HG_MODEL")
  [ -f "$HG_DIR/turned" ] && args+=(-c)
  touch "$HG_DIR/turned"
  kilo "${args[@]}" "$1"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed from the GitHub release archive (the binary and its helpers in one directory, wrapped on PATH).
- `-c` continues the last session in this directory; `KILO_PERMISSION='{"*":"allow"}'` answers every permission.
- The four `KILO_*` switches stop the model fetch, autoupdate and telemetry.
