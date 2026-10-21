# Add nanobot

nanobot, headless over `nanobot agent -m`, on an Anthropic-shaped provider through `$HOME/.nanobot/config.json`, where `${ANTHROPIC_API_KEY}` and `${ANTHROPIC_BASE_URL}` are expanded from the environment at load.

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
nanobot/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "nanobot 0.3.5, headless `nanobot agent -m`; Anthropic-, OpenAI- or custom-shaped providers.",
  "defaults": {
    "sandbox": "full",
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

## 3. Upload and run

```bash
tar czf nanobot.tgz -C nanobot .
curl -s -X PUT $HI/v1/harnesses/nanobot -H "Authorization: Bearer $KEY" --data-binary @nanobot.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "nanobot", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Installed with pip into its own venv.
- `-s $HI_SESSION` resumes the same conversation; `-w $HI_WORKSPACE` makes its tools run in the workspace (it seeds a few of its own files there).
- Its output is plain text.
