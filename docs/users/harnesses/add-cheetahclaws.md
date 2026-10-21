# Add CheetahClaws

CheetahClaws, headless over `cheetahclaws -p`, on an OpenAI chat-shaped provider through `CUSTOM_BASE_URL` and `CUSTOM_API_KEY`.

## Verified

`scripts/live.py` against a running server, sandbox `full`, provider `openai`, model `gpt-5.4-mini`:
**8 of 9** checks passed (make, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

Not passing: recall. Headless CheetahClaws starts from an empty state every run (resume is a REPL command), so each turn is a fresh conversation in the same workspace.

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/full -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM node:22-bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip git curl ca-certificates ripgrep procps tmux && rm -rf /var/lib/apt/lists/*\n", "egress": []}'
curl -s -X PUT $HI/v1/providers/openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.openai.com/v1", "api": "openai-chat", "key": "sk-…"}'
```

## 2. The folder

```
cheetahclaws/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "CheetahClaws 3.5.88, headless `cheetahclaws -p`; any OpenAI chat-shaped provider.",
  "defaults": {
    "sandbox": "full",
    "provider": "openai",
    "model": "gpt-5.4-mini"
  },
  "provider_env": {
    "key": "CUSTOM_API_KEY",
    "url": ""
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
VERSION=3.5.88
python3 -m venv "$HI_TOOLS/cc-venv"
"$HI_TOOLS/cc-venv/bin/pip" install -q --disable-pip-version-check "cheetahclaws==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../cc-venv/bin/cheetahclaws "$HI_TOOLS/bin/cheetahclaws"
"$HI_TOOLS/bin/cheetahclaws" --version || true
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
export CUSTOM_BASE_URL="${HI_PROVIDER_URL%/}" CHEETAH_PT_INPUT=0 CHEETAH_SUGGEST=0
mkdir -p "$HOME/.cheetahclaws"
[ -f "$HOME/.cheetahclaws/config.json" ] || echo '{"config_version": 2, "max_tokens": 0, "disabled_tools": ["AskUserQuestion", "EnterPlanMode", "ExitPlanMode"]}' > "$HOME/.cheetahclaws/config.json"
turn() { cheetahclaws -p "$1" -m "custom/$HI_MODEL" --accept-all </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf cheetahclaws.tgz -C cheetahclaws .
curl -s -X PUT $HI/v1/harnesses/cheetahclaws -H "Authorization: Bearer $KEY" --data-binary @cheetahclaws.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "cheetahclaws", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Installed with pip into its own venv.
- `max_tokens: 0` in its config stops it sending a `max_tokens` value newer OpenAI models refuse; the three interactive tools are disabled because nobody is there to answer them.
- Its output is terminal text rather than JSON.
