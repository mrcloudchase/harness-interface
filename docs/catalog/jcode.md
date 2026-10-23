# jcode

jcode, headless over `jcode run --ndjson`, on an Anthropic-shaped provider through `ANTHROPIC_BASE_URL` (with `/v1`) and `ANTHROPIC_API_KEY`.

## Verified

`scripts/live.py` against a running platform, provider `deepseek`, model ``: **9 of 9** checks passed (make, recall, archive, stream, interrupt accepted, steer, cancel, trace, stateless).

## Use it

```bash
curl -s -X PUT $HG/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"url": "…", "api": "…", "key": "…"}'
curl -s -X PUT $HG/v1/harnesses/jcode -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "jcode"}'
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"model": "jcode", "input": "Create hello.txt containing hello, then say done."}'
```

The package's default provider is `deepseek` and its default model `(the provider decides)`; name another with `jcode/<provider>/<model>`. The folder is `catalog/jcode/` in the repository.

## The folder

`harness.json`:

```json
{
  "contract": 5,
  "description": "jcode 0.90.0, headless `jcode run --ndjson`; an Anthropic-shaped provider.",
  "defaults": {
    "provider": "deepseek",
    "model": ""
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
VERSION=0.90.0
case "$(uname -m)" in x86_64) arch=x86_64 ;; aarch64|arm64) arch=aarch64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac
tmp=$(mktemp -d)
curl -fsSL "https://github.com/1jehuang/jcode/releases/download/v$VERSION/jcode-linux-$arch.tar.gz" -o "$tmp/jcode.tgz"
tar -xzf "$tmp/jcode.tgz" -C "$tmp"
rm -rf "$HG_TOOLS/jcode" && mkdir -p "$HG_TOOLS/jcode" "$HG_TOOLS/bin"
if [ -f "$tmp/jcode-linux-$arch.bin" ]; then
  install -m 755 "$tmp/jcode-linux-$arch" "$tmp/jcode-linux-$arch.bin" "$HG_TOOLS/jcode/"
  ln -sf "$HG_TOOLS/jcode/jcode-linux-$arch" "$HG_TOOLS/bin/jcode"
else
  install -m 755 "$tmp/jcode-linux-$arch" "$HG_TOOLS/bin/jcode"
fi
"$HG_TOOLS/bin/jcode" --version
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
export ANTHROPIC_BASE_URL="${HG_PROVIDER_URL%/v1}/v1" JCODE_NO_TELEMETRY=1 JCODE_RUN_AUTO_POKE=0 JCODE_RUNTIME_DIR=/tmp/jcode-rt
turn() {
  local args=(run --ndjson --no-update -p anthropic-api)
  [ -s "$HG_DIR/session" ] && args+=(--resume "$(cat "$HG_DIR/session")")
  [ -n "$HG_MODEL" ] && [ ! -s "$HG_DIR/session" ] && args+=(-m "$HG_MODEL")
  jcode "${args[@]}" "$1" | tee "$HG_DIR/last.jsonl"
  local rc=${PIPESTATUS[0]}
  grep -o '"session_id":"[^"]*"' "$HG_DIR/last.jsonl" | head -1 | cut -d'"' -f4 > "$HG_DIR/session.new" && [ -s "$HG_DIR/session.new" ] && mv "$HG_DIR/session.new" "$HG_DIR/session"
  return $rc
}

run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

## Notes

- Installed from the GitHub release archive, which holds a launcher and a `.bin` beside it.
- The session id is read from the first line of its output and kept in `$HG_DIR`; later turns pass `--resume`.
- jcode only accepts model ids from its own catalog, so with a non-Anthropic provider the folder sends no `-m`, and the provider maps jcode's default id to its own model. Name a catalog id in the request's model path when the provider serves one.
- It also tries to fetch a model catalog from Anthropic directly; the door refuses that and the run is unaffected.
