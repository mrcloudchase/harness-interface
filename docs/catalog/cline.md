# Cline

Cline, headless over `cline --json`, on an OpenAI-compatible provider. Headless Cline ignores base-URL variables, so the folder writes `$HOME/.cline/data/settings/providers.json` with the gateway URL and the session token as the key.

## Verified

`scripts/live.py` against a running platform, provider `deepseek-openai`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

Headless Cline cannot resume a session (that needs its ACP mode); it answers recall by looking at the workspace, not by remembering.

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek-openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/cline -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "cline"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "cline", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek-openai` and its default model `deepseek-chat`; name another with `cline/<provider>/<model>`. The folder is `catalog/cline/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "Cline 3.0.73, headless `cline --json`; an OpenAI-compatible provider through providers.json.",
  "defaults": {
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
VERSION=3.0.73
mkdir -p "$HG_TOOLS/bin"
npm install --global --prefix "$HG_TOOLS" --no-audit --no-fund "cline@$VERSION"
"$HG_TOOLS/bin/cline" --version
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
export CLINE_SESSION_BACKEND_MODE=local CLINE_NO_AUTO_UPDATE=1
mkdir -p "$HOME/.cline/data/settings"
cat > "$HOME/.cline/data/settings/providers.json" <<EOF
{"version": 1, "lastUsedProvider": "openai-compatible", "modes": {},
 "providers": {"openai-compatible": {"settings": {"provider": "openai-compatible", "apiKey": "$OPENAI_API_KEY", "model": "$HG_MODEL", "baseUrl": "${HG_PROVIDER_URL%/}"},
                                     "updatedAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "tokenSource": "manual"}}}
EOF
turn() { cline --json -y "$1" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- `CLINE_SESSION_BACKEND_MODE=local` keeps it from starting a detached hub daemon.
- The key written to `providers.json` is the session token, worthless outside the run; the real key never leaves the gateway.
- Each turn starts a fresh conversation in the same workspace, so the recall check passes by looking at the files, not by remembering; give a later turn the context it needs in the prompt.
