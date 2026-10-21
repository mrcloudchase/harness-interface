# Add OpenHands

The OpenHands CLI, headless over `openhands --headless --json`, on any litellm provider through `LLM_MODEL`, `LLM_API_KEY` and `LLM_BASE_URL`.

## Verified

`scripts/live.py` against a running server, sandbox `py312`, provider `openai`, model `gpt-5.4-mini`:
**9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/py312 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM python:3.12-slim\nRUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates tmux procps && rm -rf /var/lib/apt/lists/*\n", "egress": []}'
curl -s -X PUT $HI/v1/providers/openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.openai.com/v1", "api": "openai-chat", "key": "sk-…"}'
```

## 2. The folder

```
openhands/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "OpenHands CLI 1.16.0, headless `openhands --headless --json`; any litellm provider.",
  "defaults": {
    "sandbox": "py312",
    "provider": "openai",
    "model": "gpt-5.4-mini"
  },
  "provider_env": {
    "key": "LLM_API_KEY",
    "url": ""
  },
  "interrupt": "SIGUSR1",
  "install": {
    "egress": [
      "pypi.org",
      "files.pythonhosted.org"
    ],
    "timeout_s": 1800
  },
  "run": {
    "timeout_s": 2400,
    "stop_timeout_s": 20
  }
}
```

`install.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
VERSION=1.16.0
python3 -m venv "$HI_TOOLS/oh-venv"
"$HI_TOOLS/oh-venv/bin/pip" install -q --disable-pip-version-check "openhands==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../oh-venv/bin/openhands "$HI_TOOLS/bin/openhands"
"$HI_TOOLS/bin/openhands" --version || true
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
export LLM_MODEL="openai/$HI_MODEL" LLM_BASE_URL="${HI_PROVIDER_URL%/}" PYTHONUNBUFFERED=1 TERM=dumb OPENHANDS_SUPPRESS_BANNER=1
export LITELLM_LOCAL_MODEL_COST_MAP=True
turn() { openhands --headless --json --override-with-envs --resume "$(sid_uuid)" -t "$1" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf openhands.tgz -C openhands .
curl -s -X PUT $HI/v1/harnesses/openhands -H "Authorization: Bearer $KEY" --data-binary @openhands.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "openhands", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Needs Python 3.12, hence the `py312` sandbox. The first start is slow (it unpacks and initializes); `run.timeout_s` is raised to allow it.
- The conversation id is derived from the platform session as a UUID and passed as `--resume` on every turn, so turn one creates it and later turns continue it.
- `openai/<model>` for a chat or Responses provider; `anthropic/<model>` with a base without `/v1` for an Anthropic one.
