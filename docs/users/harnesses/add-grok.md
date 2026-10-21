# Add Grok Build

Grok Build, headless over `grok -p --output-format streaming-json`, on any provider through a `[model.hi]` entry in `$HOME/.grok/config.toml` whose `env_key` names the variable holding the credential.

## Verified

`scripts/live.py` against a running server, sandbox `full`, provider `deepseek-openai`, model `deepseek-chat`:
**9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/full -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM node:22-bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip git curl ca-certificates ripgrep procps tmux && rm -rf /var/lib/apt/lists/*\n", "egress": []}'
curl -s -X PUT $HI/v1/providers/deepseek-openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/v1", "api": "openai-chat", "key": "sk-…"}'
```

## 2. The folder

```
grok/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "Grok Build 1.0.41, headless `grok -p --output-format streaming-json`; chat-, Responses- or Anthropic-shaped providers.",
  "defaults": {
    "sandbox": "full",
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
mkdir -p "$HI_TOOLS/bin"
curl -fsSL "https://x.ai/cli/grok-$VERSION-linux-$arch" -o "$HI_TOOLS/bin/grok" \
  || curl -fsSL "https://storage.googleapis.com/grok-build-public-artifacts/cli/grok-$VERSION-linux-$arch" -o "$HI_TOOLS/bin/grok"
chmod 755 "$HI_TOOLS/bin/grok"
"$HI_TOOLS/bin/grok" --version
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
export GROK_FOLDER_TRUST=0 GROK_DISABLE_AUTOUPDATER=1
mkdir -p "$HOME/.grok"
cat > "$HOME/.grok/config.toml" <<EOF
[models]
session_summary = "hi"
prompt_suggestion = "hi"
[model.hi]
model = "$HI_MODEL"
base_url = "${HI_PROVIDER_URL%/}"
env_key = "OPENAI_API_KEY"
api_backend = "chat_completions"
EOF
turn() {
  local args=(-p "$1" -m hi --output-format streaming-json --permission-mode bypassPermissions)
  if [ -f "$HI_DIR/turned" ]; then args+=(--resume "$(sid_uuid)"); else args+=(-s "$(sid_uuid)"); fi
  touch "$HI_DIR/turned"
  grok "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf grok.tgz -C grok .
curl -s -X PUT $HI/v1/harnesses/grok -H "Authorization: Bearer $KEY" --data-binary @grok.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "grok", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Installed from the single static binary x.ai publishes.
- `-s <uuid>` on the first turn and `--resume <uuid>` after, the UUID derived from the platform session id.
- `api_backend = "chat_completions"` here; `responses` or `messages` for the other shapes.
- `GROK_FOLDER_TRUST=0` lets it read `AGENTS.md` from the workspace; `GROK_DISABLE_AUTOUPDATER=1` keeps it off the network.
- Assistant text arrives as `text` events with token-sized `data`; join them to read it.
