# Add zeroclaw

zeroclaw, one-shot over `zeroclaw agent -m`, on an OpenAI chat-shaped provider through a `[providers.models.custom.hi]` entry in a config directory the folder writes each turn; the credential travels in the environment variable zeroclaw derives from that key path.

## Verified

`scripts/live.py` against a running server, sandbox `full`, provider `deepseek-openai`, model `deepseek-chat`:
**7 of 9** checks passed (make, archive, interrupt accepted, steer, cancel, trace, stateless).

Not passing: recall, stream. One-shot zeroclaw keeps no conversation between runs (resume needs its ACP server), so each turn starts fresh in the same workspace, and it prints its answer in one write at the end, so a streamed response arrives as one chunk.

## 1. Sandbox and provider

```bash
curl -s -X PUT $HI/v1/sandboxes/full -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM node:22-bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv python3-pip git curl ca-certificates ripgrep procps tmux && rm -rf /var/lib/apt/lists/*\n", "egress": []}'
curl -s -X PUT $HI/v1/providers/deepseek-openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/v1", "api": "openai-chat", "key": "sk-…"}'
```

## 2. The folder

```
zeroclaw/
  harness.json
  install.sh
  request.sh
```

`harness.json`:

```json
{
  "contract": 3,
  "description": "zeroclaw 0.8.5, one-shot `zeroclaw agent -m`; an OpenAI chat-shaped provider.",
  "defaults": {
    "sandbox": "full",
    "provider": "deepseek-openai",
    "model": "deepseek-chat"
  },
  "provider_env": {
    "key": "ZEROCLAW_providers__models__custom__hi__api_key",
    "url": ""
  },
  "interrupt": "SIGUSR1",
  "install": {
    "egress": [
      "github.com",
      "objects.githubusercontent.com",
      "release-assets.githubusercontent.com"
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
VERSION=0.8.5
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/zeroclaw-labs/zeroclaw/releases/download/v$VERSION/zeroclaw-$arch-unknown-linux-gnu.tar.gz" -o "$tmp/zc.tgz"
tar -xzf "$tmp/zc.tgz" -C "$tmp" zeroclaw
mkdir -p "$HI_TOOLS/bin" && install -m 755 "$tmp/zeroclaw" "$HI_TOOLS/bin/zeroclaw"
"$HI_TOOLS/bin/zeroclaw" --version
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
mkdir -p "$HI_DIR/zc"
cat > "$HI_DIR/zc/config.toml" <<EOF
schema_version = 3
[providers.models.custom.hi]
uri = "${HI_PROVIDER_URL%/}"
model = "$HI_MODEL"
native_tools = true
[agents.zeroclaw]
enabled = true
model_provider = "custom.hi"
risk_profile = "hi"
[agents.zeroclaw.workspace]
path = "$HI_WORKSPACE"
[risk_profiles.hi]
level = "full"
allowed_commands = ["*"]
block_high_risk_commands = false
workspace_only = false
forbidden_paths = []
EOF
turn() { zeroclaw agent --agent zeroclaw --config-dir "$HI_DIR/zc" -m "$1" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## 3. Upload and run

```bash
tar czf zeroclaw.tgz -C zeroclaw .
curl -s -X PUT $HI/v1/harnesses/zeroclaw -H "Authorization: Bearer $KEY" --data-binary @zeroclaw.tgz
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "zeroclaw", "input": "Create hello.txt containing hello, then say done."}'
```

## Notes

- Installed from the GitHub release archive.
- `native_tools = true` makes it use the provider's tool calls rather than prompt-guided ones.
- The risk profile allows every command; the container is the boundary.
