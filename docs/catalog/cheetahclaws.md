# CheetahClaws

CheetahClaws, headless over `cheetahclaws -p`, on an OpenAI chat-shaped provider through `CUSTOM_BASE_URL` and `CUSTOM_API_KEY`.

## Verified

`scripts/live.py` against a running platform, provider `openai`, model `gpt-5.4-mini`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

Headless CheetahClaws starts from an empty conversation every run (resume is a REPL command); it answers recall by looking at the workspace, not by remembering.

## Use it

```bash
curl -s -X PUT $HI/v1/providers/openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/cheetahclaws -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "cheetahclaws"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "cheetahclaws", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `openai` and its default model `gpt-5.4-mini`; name another with `cheetahclaws/<provider>/<model>`. The folder is `catalog/cheetahclaws/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "CheetahClaws 3.5.88, headless `cheetahclaws -p`; any OpenAI chat-shaped provider.",
  "defaults": {
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
VERSION=3.5.88
python3 -m venv "$HI_TOOLS/cc-venv"
"$HI_TOOLS/cc-venv/bin/pip" install -q --disable-pip-version-check "cheetahclaws==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../cc-venv/bin/cheetahclaws "$HI_TOOLS/bin/cheetahclaws"
"$HI_TOOLS/bin/cheetahclaws" --version || true
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
export CUSTOM_BASE_URL="${HI_PROVIDER_URL%/}" CHEETAH_PT_INPUT=0 CHEETAH_SUGGEST=0
mkdir -p "$HOME/.cheetahclaws"
[ -f "$HOME/.cheetahclaws/config.json" ] || echo '{"config_version": 2, "max_tokens": 0, "disabled_tools": ["AskUserQuestion", "EnterPlanMode", "ExitPlanMode"]}' > "$HOME/.cheetahclaws/config.json"
turn() { cheetahclaws -p "$1" -m "custom/$HI_MODEL" --accept-all </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed with pip into its own venv.
- `max_tokens: 0` in its config stops it sending a `max_tokens` value newer OpenAI models refuse; the three interactive tools are disabled because nobody is there to answer them.
- Its output is terminal text rather than JSON.
