# zeroclaw

zeroclaw, one-shot over `zeroclaw agent -m`, on an OpenAI chat-shaped provider through a `[providers.models.custom.hi]` entry in a config directory the folder writes each turn; the credential travels in the environment variable zeroclaw derives from that key path.

## Verified

`scripts/live.py` against a running platform, provider `deepseek-openai`, model `deepseek-chat`: **7 of 9** checks passed (make, archive, interrupt accepted, steer, cancel, trace, stateless).

Not passing: recall, stream. One-shot zeroclaw keeps no conversation between runs (resume needs its ACP server), so each turn starts fresh in the same workspace, and it prints its answer in one write at the end, so a streamed response arrives as one chunk.

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek-openai -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/zeroclaw -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "zeroclaw"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "zeroclaw", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek-openai` and its default model `deepseek-chat`; name another with `zeroclaw/<provider>/<model>`. The folder is `catalog/zeroclaw/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "zeroclaw 0.8.5, one-shot `zeroclaw agent -m`; an OpenAI chat-shaped provider.",
  "defaults": {
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
VERSION=0.8.5
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/zeroclaw-labs/zeroclaw/releases/download/v$VERSION/zeroclaw-$arch-unknown-linux-gnu.tar.gz" -o "$tmp/zc.tgz"
tar -xzf "$tmp/zc.tgz" -C "$tmp" zeroclaw
mkdir -p "$HG_TOOLS/bin" && install -m 755 "$tmp/zeroclaw" "$HG_TOOLS/bin/zeroclaw"
"$HG_TOOLS/bin/zeroclaw" --version
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
mkdir -p "$HG_DIR/zc"
cat > "$HG_DIR/zc/config.toml" <<EOF
schema_version = 3
[providers.models.custom.hi]
uri = "${HG_PROVIDER_URL%/}"
model = "$HG_MODEL"
native_tools = true
[agents.zeroclaw]
enabled = true
model_provider = "custom.hi"
risk_profile = "hi"
[agents.zeroclaw.workspace]
path = "$HG_WORKSPACE"
[risk_profiles.hi]
level = "full"
allowed_commands = ["*"]
block_high_risk_commands = false
workspace_only = false
forbidden_paths = []
EOF
turn() { zeroclaw agent --agent zeroclaw --config-dir "$HG_DIR/zc" -m "$1" </dev/null; }

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed from the GitHub release archive.
- `native_tools = true` makes it use the provider's tool calls rather than prompt-guided ones.
- The risk profile allows every command; the container is the boundary.
