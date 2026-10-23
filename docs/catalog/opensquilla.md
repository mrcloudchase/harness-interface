# OpenSquilla

OpenSquilla, headless over `opensquilla agent --json`, on an Anthropic-shaped provider through `$HOME/.opensquilla/config.toml`, where `api_key_env` names the credential's variable.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **8 of 9** checks passed (make, recall, archive, interrupt accepted, steer, cancel, trace, stateless).

Not passing: stream. OpenSquilla prints its answer as one JSON line at the end of the turn, so a streamed response arrives as one chunk rather than many.

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/opensquilla -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "opensquilla"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "opensquilla", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `opensquilla/<provider>/<model>`. The folder is `catalog/opensquilla/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "OpenSquilla 0.5.6, headless `opensquilla agent --json`; Anthropic- or Responses-shaped providers.",
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
      "release-assets.githubusercontent.com",
      "pypi.org",
      "files.pythonhosted.org"
    ],
    "timeout_s": 1500
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
VERSION=0.5.6
tmp=$(mktemp -d)
whl="opensquilla-$VERSION-py3-none-any.whl"
curl -fsSL "https://github.com/TokenRhythm/opensquilla/releases/download/v$VERSION/$whl" -o "$tmp/$whl"
python3 -m venv "$HG_TOOLS/sq-venv"
"$HG_TOOLS/sq-venv/bin/pip" install -q --disable-pip-version-check "$tmp/$whl"
mkdir -p "$HG_TOOLS/bin" && ln -sf ../sq-venv/bin/opensquilla "$HG_TOOLS/bin/opensquilla"
"$HG_TOOLS/bin/opensquilla" --help >/dev/null
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
export OPENSQUILLA_UPDATE_CHECK_DISABLED=1 ORT_DISABLE_TELEMETRY=1
mkdir -p "$HOME/.opensquilla"
cat > "$HOME/.opensquilla/config.toml" <<EOF
[llm]
provider = "anthropic"
model = "$HG_MODEL"
api_key_env = "ANTHROPIC_API_KEY"
base_url = "${HG_PROVIDER_URL%/v1}"
[squilla_router]
enabled = false
EOF
turn() { opensquilla agent -m "$1" --json --permissions bypass --workspace "$HG_WORKSPACE" --stateless-keep-project-rules --session-id "$HG_SESSION" --session-db-path "$HOME/.opensquilla/sessions.db"; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Needs Python 3.12, hence the `py312` sandbox; installed from the wheel its GitHub release publishes.
- `--session-id $HG_SESSION` with a session database in the member's home resumes across turns.
- `--stateless-keep-project-rules` stops it seeding persona files into the workspace.
