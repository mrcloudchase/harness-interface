# OpenHands

The OpenHands CLI, headless over `openhands --headless --json`, on any litellm provider through `LLM_MODEL`, `LLM_API_KEY` and `LLM_BASE_URL`.

## Verified

`scripts/live.py` against a running platform, provider `openai`, model `gpt-5.4-mini`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/openhands -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "openhands"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "openhands", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `openai` and its default model `gpt-5.4-mini`; name another with `openhands/<provider>/<model>`. The folder is `catalog/openhands/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "OpenHands CLI 1.16.0, headless `openhands --headless --json`; any litellm provider.",
  "defaults": {
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
    "egress": [],
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
export LLM_MODEL="openai/$HI_MODEL" LLM_BASE_URL="${HI_PROVIDER_URL%/}" PYTHONUNBUFFERED=1 TERM=dumb OPENHANDS_SUPPRESS_BANNER=1
export LITELLM_LOCAL_MODEL_COST_MAP=True
turn() { openhands --headless --json --override-with-envs --resume "$(sid_uuid)" -t "$1" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Needs Python 3.12, hence the `py312` sandbox. The first start is slow (it unpacks and initializes); `run.timeout_s` is raised to allow it.
- The conversation id is derived from the platform session as a UUID and passed as `--resume` on every turn, so turn one creates it and later turns continue it.
- `openai/<model>` for a chat or Responses provider; `anthropic/<model>` with a base without `/v1` for an Anthropic one.
