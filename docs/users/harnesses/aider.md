# aider

aider, one turn per `--message`, on an OpenAI chat-shaped provider through `OPENAI_API_BASE` and `OPENAI_API_KEY`. The chat history file lives in `$HI_DIR`, and later turns pass `--restore-chat-history`.

## Verified

`scripts/live.py` against a running platform, provider `deepseek-openai`, model `deepseek-chat`: **8 of 9** checks passed (make, recall, archive, stream, interrupt accepted, cancel, trace, stateless).

Not passing: steer. aider has no shell tool: a task that asks it to run a command is answered with a script to run instead, so the counting turn ends at once and the steer, delivered after the turn, finds nothing to interrupt. That is aider's shape, not a platform fault; cancel and the rest work.

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek-openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/aider -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "aider"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "aider", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek-openai` and its default model `deepseek-chat`; name another with `aider/<provider>/<model>`. The folder is [`catalog/aider/`](../../../catalog/aider/).

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "aider 0.86.2, one turn per `--message`; Anthropic- or OpenAI chat-shaped providers.",
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
VERSION=0.86.2
python3 -m venv "$HI_TOOLS/aider-venv"
"$HI_TOOLS/aider-venv/bin/pip" install -q --disable-pip-version-check "aider-chat==$VERSION"
mkdir -p "$HI_TOOLS/bin" && ln -sf ../aider-venv/bin/aider "$HI_TOOLS/bin/aider"
"$HI_TOOLS/bin/aider" --version
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
export OPENAI_API_BASE="${HI_PROVIDER_URL%/}" LITELLM_LOCAL_MODEL_COST_MAP=True AIDER_ANALYTICS_DISABLE=1
turn() {
  local args=(--model "openai/$HI_MODEL" --message "$1" --yes-always --no-pretty --no-stream --no-git --no-fancy-input
              --no-show-model-warnings --no-check-update --no-show-release-notes --analytics-disable
              --chat-history-file "$HI_DIR/chat.history.md" --input-history-file "$HI_DIR/input.history" --llm-history-file "$HI_DIR/llm.history")
  [ -f "$HI_DIR/turned" ] && args+=(--restore-chat-history)
  touch "$HI_DIR/turned"
  aider "${args[@]}" </dev/null
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed with pip into its own venv.
- `--no-git` because the workspace is not a repository; drop it when it is, and aider will stage what it edits.
- `openai/<model>` routes through litellm's OpenAI path; `anthropic/<model>` with `ANTHROPIC_API_BASE` (no `/v1`) for an Anthropic-shaped provider.
- The litellm model-price fetch it logs at start is refused by the door and harmless; DeepSeek's chat model edits reliably in its `whole` format, which is why it is the default here.
