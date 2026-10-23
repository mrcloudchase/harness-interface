# Grok Build

Grok Build, headless over `grok -p --output-format streaming-json`, on any provider through a `[model.hi]` entry in `$HOME/.grok/config.toml` whose `env_key` names the variable holding the credential.

## Verified

`scripts/live.py` against a running platform, provider `deepseek-openai`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek-openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/grok -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "grok"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "grok", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek-openai` and its default model `deepseek-chat`; name another with `grok/<provider>/<model>`. The folder is `catalog/grok/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "Grok Build 1.0.41, headless `grok -p --output-format streaming-json`; chat-, Responses- or Anthropic-shaped providers.",
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
      "x.ai",
      "storage.googleapis.com"
    ],
    "timeout_s": 1200
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
VERSION=1.0.41
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
mkdir -p "$HG_TOOLS/bin"
curl -fsSL "https://x.ai/cli/grok-$VERSION-linux-$arch" -o "$HG_TOOLS/bin/grok" \
  || curl -fsSL "https://storage.googleapis.com/grok-build-public-artifacts/cli/grok-$VERSION-linux-$arch" -o "$HG_TOOLS/bin/grok"
chmod 755 "$HG_TOOLS/bin/grok"
"$HG_TOOLS/bin/grok" --version
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
export GROK_FOLDER_TRUST=0 GROK_DISABLE_AUTOUPDATER=1
mkdir -p "$HOME/.grok"
cat > "$HOME/.grok/config.toml" <<EOF
[models]
session_summary = "hi"
prompt_suggestion = "hi"
[model.hi]
model = "$HG_MODEL"
base_url = "${HG_PROVIDER_URL%/}"
env_key = "OPENAI_API_KEY"
api_backend = "chat_completions"
EOF
turn() {
  local args=(-p "$1" -m hi --output-format streaming-json --permission-mode bypassPermissions)
  if [ -f "$HG_DIR/turned" ]; then args+=(--resume "$(sid_uuid)"); else args+=(-s "$(sid_uuid)"); fi
  touch "$HG_DIR/turned"
  grok "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed from the single static binary x.ai publishes.
- `-s <uuid>` on the first turn and `--resume <uuid>` after, the UUID derived from the platform session id.
- `api_backend = "chat_completions"` here; `responses` or `messages` for the other shapes.
- `GROK_FOLDER_TRUST=0` lets it read `AGENTS.md` from the workspace; `GROK_DISABLE_AUTOUPDATER=1` keeps it off the network.
- Assistant text arrives as `text` events with token-sized `data`; join them to read it.
