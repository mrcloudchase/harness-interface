# Add Cline

Cline, headless over `cline --json`, on an OpenAI-compatible provider. Headless Cline ignores base-URL variables, so the folder writes `$HOME/.cline/data/settings/providers.json` with the gateway URL and the session token as the key.

## Verified

`scripts/live.py` against a running server, sandbox `node22`, provider `deepseek-openai`, model `deepseek-chat`:
**9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

Headless Cline cannot resume a session (that needs its ACP mode).

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/node22 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"image": "node:22-bookworm-slim", "egress": []}'
curl -s -X PUT $HI/v1/providers/deepseek-openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/v1", "api": "openai-chat", "key": "sk-…"}'
```

## 2. The folder

```
cline/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "Cline 3.0.73, headless `cline --json`; an OpenAI-compatible provider through providers.json.",
  "defaults": {
    "sandbox": "node22",
    "provider": "deepseek-openai",
    "model": "deepseek-chat"
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
VERSION=3.0.73
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "cline@$VERSION"
"$HI_TOOLS/bin/cline" --version
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
export CLINE_SESSION_BACKEND_MODE=local CLINE_NO_AUTO_UPDATE=1
mkdir -p "$HOME/.cline/data/settings"
cat > "$HOME/.cline/data/settings/providers.json" <<EOF
{"version": 1, "lastUsedProvider": "openai-compatible", "modes": {},
 "providers": {"openai-compatible": {"settings": {"provider": "openai-compatible", "apiKey": "$OPENAI_API_KEY", "model": "$HI_MODEL", "baseUrl": "${HI_PROVIDER_URL%/}"},
                                     "updatedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "tokenSource": "manual"}}}
EOF
turn() { cline --json -y "$1" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf cline.tgz -C cline .
curl -s -X PUT $HI/v1/harnesses/cline -H "Authorization: Bearer $KEY" --data-binary @cline.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "cline", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- `CLINE_SESSION_BACKEND_MODE=local` keeps it from starting a detached hub daemon.
- The key written to `providers.json` is the session token, worthless outside the run; the real key never leaves the gateway.
- Each turn starts a fresh conversation in the same workspace, so the recall check passes by looking at the files, not by remembering; give a later turn the context it needs in the prompt.
