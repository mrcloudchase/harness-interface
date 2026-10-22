# nanobot

nanobot, headless over `nanobot agent -m`, on an Anthropic-shaped provider through `$HOME/.nanobot/config.json`, where `${ANTHROPIC_API_KEY}` and `${ANTHROPIC_BASE_URL}` are expanded from the environment at load.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/nanobot -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "nanobot"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "nanobot", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `nanobot/<provider>/<model>`. The folder is [`catalog/nanobot/`](../../../catalog/nanobot/).

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "nanobot 0.3.5, headless `nanobot agent -m`; Anthropic-, OpenAI- or custom-shaped providers.",
  "defaults": {
    "provider": "deepseek",
    "model": "deepseek-chat"
  },
  "provider_env": {
    "key": "ANTHROPIC_API_KEY",
    "url": "ANTHROPIC_BASE_URL"
  },
  "interrupt": "SIGUSR1",
  "install": {
    "egress": [
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
VERSION=0.3.5
python3 -m venv "$HI_TOOLS/nb-venv"
"$HI_TOOLS/nb-venv/bin/pip" install -q --disable-pip-version-check "nanobot-ai==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../nb-venv/bin/nanobot "$HI_TOOLS/bin/nanobot"
"$HI_TOOLS/bin/nanobot" --version
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
mkdir -p "$HOME/.nanobot"
cat > "$HOME/.nanobot/config.json" <<EOF
{"providers": {"anthropic": {"apiKey": "\${ANTHROPIC_API_KEY}", "apiBase": "\${ANTHROPIC_BASE_URL}"}},
 "agents": {"defaults": {"provider": "anthropic", "model": "anthropic/$HI_MODEL", "workspace": "$HI_WORKSPACE"}}}
EOF
turn() { nanobot agent --no-markdown -m "$1" -s "$HI_SESSION" -w "$HI_WORKSPACE" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed with pip into its own venv.
- `-s $HI_SESSION` resumes the same conversation; `-w $HI_WORKSPACE` makes its tools run in the workspace (it seeds a few of its own files there).
- Its output is plain text.
