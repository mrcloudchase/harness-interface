# Add OpenSquilla

OpenSquilla, headless over `opensquilla agent --json`, on an Anthropic-shaped provider through `$HOME/.opensquilla/config.toml`, where `api_key_env` names the credential's variable.

## Verified

`scripts/live.py` against a running server, sandbox `py312`, provider `deepseek`, model `deepseek-chat`:
**9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/py312 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM python:3.12-slim\nRUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates tmux procps && rm -rf /var/lib/apt/lists/*\n", "egress": []}'
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/anthropic", "api": "anthropic-messages", "key": "sk-…"}'
```

## 2. The folder

```
opensquilla/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "OpenSquilla 0.5.6, headless `opensquilla agent --json`; Anthropic- or Responses-shaped providers.",
  "defaults": {
    "sandbox": "py312",
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
      "release-assets.githubusercontent.com",
      "pypi.org",
      "files.pythonhosted.org"
    ],
    "timeout_s": 1500
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
VERSION=0.5.6
tmp=$(mktemp -d)
whl="opensquilla-$VERSION-py3-none-any.whl"
curl -fsSL "https://github.com/TokenRhythm/opensquilla/releases/download/v$VERSION/$whl" -o "$tmp/$whl"
python3 -m venv "$HI_TOOLS/sq-venv"
"$HI_TOOLS/sq-venv/bin/pip" install -q --disable-pip-version-check "$tmp/$whl"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../sq-venv/bin/opensquilla "$HI_TOOLS/bin/opensquilla"
"$HI_TOOLS/bin/opensquilla" --help >/dev/null
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
export OPENSQUILLA_UPDATE_CHECK_DISABLED=1 ORT_DISABLE_TELEMETRY=1
mkdir -p "$HOME/.opensquilla"
cat > "$HOME/.opensquilla/config.toml" <<EOF
[llm]
provider = "anthropic"
model = "$HI_MODEL"
api_key_env = "ANTHROPIC_API_KEY"
base_url = "${HI_PROVIDER_URL%/v1}"
[squilla_router]
enabled = false
EOF
turn() { opensquilla agent -m "$1" --json --permissions bypass --workspace "$HI_WORKSPACE" --stateless-keep-project-rules --session-id "$HI_SESSION" --session-db-path "$HOME/.opensquilla/sessions.db"; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf opensquilla.tgz -C opensquilla .
curl -s -X PUT $HI/v1/harnesses/opensquilla -H "Authorization: Bearer $KEY" --data-binary @opensquilla.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "opensquilla", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Needs Python 3.12, hence the `py312` sandbox; installed from the wheel its GitHub release publishes.
- `--session-id $HI_SESSION` with a session database in the member's home resumes across turns.
- `--stateless-keep-project-rules` stops it seeding persona files into the workspace.
