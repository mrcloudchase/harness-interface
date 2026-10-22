# Hermes Agent

Nous Research's Hermes Agent, headless over `hermes chat -q`, on an Anthropic-shaped provider. The `Session:` line it prints at exit is kept in `$HI_DIR` and later turns pass `--resume`.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HI/v1/harnesses/hermes -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "hermes"}'
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "hermes", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `hermes/<provider>/<model>`. The folder is [`catalog/hermes/`](../../../catalog/hermes/).

## The folder

`harness.json`:

```json
{
  "contract": 4,
  "description": "Hermes Agent 0.19.0, headless `hermes chat -q`; any Anthropic-shaped provider.",
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
VERSION=0.19.0
mkdir -p "$HI_TOOLS/bin"
python3 -m venv "$HI_TOOLS/hermes-venv"
"$HI_TOOLS/hermes-venv/bin/pip" install -q --disable-pip-version-check "hermes-agent[anthropic]==$VERSION"
ln -sf ../hermes-venv/bin/hermes "$HI_TOOLS/bin/hermes"
"$HI_TOOLS/bin/hermes" --version
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
export HERMES_HOME="$HOME/.hermes" TIRITH_ENABLED=0 HERMES_YOLO_MODE=1 HERMES_INFERENCE_PROVIDER=anthropic
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL%/v1}"
mkdir -p "$HERMES_HOME"
cat > "$HERMES_HOME/config.yaml" <<EOF
model:
  provider: anthropic
  base_url: ${ANTHROPIC_BASE_URL}
  default: ${HI_MODEL}
  context_length: 128000
security:
  tirith_enabled: false
memory:
  nudge_interval: 0
skills:
  creation_nudge_interval: 0
agent:
  verify_on_stop: false
EOF
turn() {
  local args=(chat -q "$1" --yolo --provider anthropic -m "$HI_MODEL" --no-restore-cwd)
  [ -s "$HI_DIR/session" ] && args+=(--resume "$(cat "$HI_DIR/session")")
  hermes "${args[@]}" | tee "$HI_DIR/out"
  local rc=${PIPESTATUS[0]}
  sed -n 's/^Session: *//p' "$HI_DIR/out" | tail -1 > "$HI_DIR/session.new" && [ -s "$HI_DIR/session.new" ] && mv "$HI_DIR/session.new" "$HI_DIR/session"
  return $rc
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed with pip into its own venv (`hermes-agent[anthropic]`). `config.yaml` under `$HERMES_HOME` is rewritten every turn with the provider's base URL and the model.
- `--no-restore-cwd` keeps a resumed session in the current workspace rather than the directory it was recorded in.
- `tirith_enabled: false` and the two `nudge_interval: 0` settings stop its scanner download and its background memory review, which would otherwise make model calls after the turn ends.
- Hermes also speaks OpenAI-chat providers (`--provider openai-api`); change the provider block in `config.yaml` and `provider_env` accordingly.
