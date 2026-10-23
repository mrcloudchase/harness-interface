# goose

goose, headless over `goose run`, on an Anthropic-shaped provider through `GOOSE_PROVIDER`, `GOOSE_MODEL` and `ANTHROPIC_HOST`.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model `deepseek-chat`: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/goose -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "goose"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "goose", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `deepseek-chat`; name another with `goose/<provider>/<model>`. The folder is `catalog/goose/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "goose 1.50.0, headless `goose run`; Anthropic- or OpenAI-shaped providers.",
  "defaults": {
    "provider": "deepseek",
    "model": "deepseek-chat"
  },
  "provider_env": {
    "key": "ANTHROPIC_API_KEY",
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
VERSION=1.50.0
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/aaif-goose/goose/releases/download/v$VERSION/goose-$arch-unknown-linux-gnu.tar.gz" -o "$tmp/goose.tgz"
tar -xzf "$tmp/goose.tgz" -C "$tmp"
mkdir -p "$HG_TOOLS/bin" && install -m 755 "$tmp/goose" "$HG_TOOLS/bin/goose"
"$HG_TOOLS/bin/goose" --version
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
export GOOSE_PROVIDER=anthropic GOOSE_MODEL="$HG_MODEL" ANTHROPIC_HOST="${HG_PROVIDER_URL%/v1}" GOOSE_DISABLE_SESSION_NAMING=1 RUST_BACKTRACE=0
export GOOSE_MODE=auto
turn() {
  local args=(run -t "$1" --output-format stream-json -n "$HG_SESSION")
  [ -f "$HG_DIR/turned" ] && args+=(-r)
  touch "$HG_DIR/turned"
  goose "${args[@]}"
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Sessions are named after the platform session (`-n $HG_SESSION`) and resumed with `-r`.
- `ANTHROPIC_HOST` is the base without `/v1`; for an OpenAI provider set `GOOSE_PROVIDER=openai` and `OPENAI_BASE_URL` with `/v1`.
- `GOOSE_MODE=auto` approves every tool call; `GOOSE_DISABLE_SESSION_NAMING=1` saves a model call per turn.
- Its stream-json output starts with a three-line text banner; a program reading it should skip lines that are not JSON.
- Assistant text arrives token-chunked across `message` events; join the `text` fields to read it.
