# Write a package

A harness package is a folder. The platform reads one file from it, runs two, copies the rest,
and never reads what the scripts print.

```
my-harness/
  harness.json      what the platform needs to launch it: defaults, variable names, the signal, egress, timeouts
  install.sh        puts the CLI into $HI_TOOLS, once per package version, unprivileged, in the base image
  request.sh        runs one turn: the prompt on stdin, stdout relayed live, both streams kept
  response.sh       optional: decides what the response carries, from request.sh's streams and exit code
  seeds/org/        copied into $HOME on every turn, overwriting: managed settings
  seeds/user/       copied into $HOME on a member's first use only: a starting point that becomes theirs
  seeds/project/    copied into the workspace when a session starts, only where no file exists
```

Start from `catalog/template/` in the repository, the smallest complete package, or from the
catalog package closest to your CLI.

## harness.json

```json
{
  "contract": 4,
  "description": "Claude Code, headless",
  "defaults": {"provider": "deepseek", "model": "deepseek-chat"},
  "provider_env": {"key": "ANTHROPIC_API_KEY", "url": "ANTHROPIC_BASE_URL"},
  "interrupt": "SIGUSR1",
  "install": {"egress": ["registry.npmjs.org"], "timeout_s": 1200},
  "run": {"egress": [], "timeout_s": 1800, "stop_timeout_s": 20}
}
```

| Key | Meaning |
|---|---|
| `defaults` | The provider and model a request with a bare harness name uses; `harness/provider/model` names its own. The model is whatever id the provider serves. Either may be empty; a request must then name it. |
| `provider_env` | Variable names to put the session token and the gateway URL in, so the CLI finds its credential where it looks. Optional: `HI_PROVIDER_KEY_FILE` and `HI_PROVIDER_URL` are always set. |
| `interrupt` | The signal a steer sends to `request.sh` after writing `$HI_DIR/interrupt`: `SIGUSR1`, `SIGUSR2`, `SIGINT` or `SIGHUP`. Never `SIGTERM`, which is a stop. |
| `install.egress` | Hosts `install.sh` may reach. `install.timeout_s`: its cap, within the tenant's ceiling. |
| `run.egress` | Hosts a turn may reach besides its provider, which is injected and never listed. Public addresses only. |
| `run.timeout_s` | A turn's wall-clock cap, within the tenant's ceiling; past it the turn is `incomplete`. `run.stop_timeout_s`: how long a cancel waits after `SIGTERM` before `SIGKILL`. |

Unknown keys are refused by name. Every key but `contract` has a default.

## install.sh

Runs once per package version on each worker, as the tenant's unprivileged uid, in the base
image, with `$HI_TOOLS` writable and egress to `install.egress` only. Put the CLI under
`$HI_TOOLS`; `$HI_TOOLS/bin` is on `PATH` at run time. Pin the version.

```bash
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@2.1.305"
```

The base image has Debian, Python 3.12, Node 22, git, curl, ripgrep, procps and tmux. A Python
CLI goes in a virtualenv under `$HI_TOOLS` with a link in `$HI_TOOLS/bin`. A failed install
fails the turn with the log's tail in `error`, and the next turn tries again.

## request.sh

One turn. The prompt is on stdin. Its stdout is relayed live to a streaming client and kept;
its stderr is kept; its exit code is kept. It runs in the workspace as the tenant's uid.

| Variable | Value |
|---|---|
| stdin | the prompt: the request's text. Its files are already in the workspace. |
| `HI_WORKSPACE` | the working directory, kept between turns of a stored session |
| `HOME` | the member's home for this package, seeded, kept between sessions |
| `HI_DIR` | a run directory: `$HI_DIR/prompt` is the prompt; `$HI_DIR/interrupt` is a steer's text when one arrives |
| `HI_REQUEST` | the request body, as sent, as a JSON file: every field, present or future |
| `HI_SESSION`, `HI_RESPONSE` | the session's and the response's ids |
| `HI_TURN` | 1 for a session's first turn, then 2, 3… so the script knows to resume |
| `HI_MODEL` | the model to use |
| `HI_INSTRUCTIONS` | the request's `instructions`, if any |
| `HI_PROVIDER_URL`, `HI_PROVIDER_KEY_FILE` | the gateway's URL, with the provider's path, and a file holding the session token; plus `provider_env`'s names set to the same |
| `HI_HARNESS_DIR`, `HI_TOOLS`, `PATH` | the package, the tools layer, `$HI_TOOLS/bin` first |
| `HI_INTERRUPT` | the signal name from `harness.json` |

The catalog's packages share one skeleton:

```bash
#!/usr/bin/env bash
set -uo pipefail
prompt=$(cat)
run_wait() { "$@" </dev/null & local pid=$! rc; while :; do wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null || break; done; return $rc; }
steer=""
trap 'steer=$(cat "$HI_DIR/interrupt" 2>/dev/null || true)' USR1
turn() {                                  # the CLI-specific part: resume on later turns, run the task
  local args=(-p "$1" --output-format stream-json --model "$HI_MODEL")
  [ "$HI_TURN" -gt 1 ] && args+=(--continue)
  claude "${args[@]}"
}
run_wait turn "$prompt"; rc=$?
if [ -n "$steer" ]; then run_wait turn "$steer"; rc=$?; fi
exit $rc
```

A steer delivers the signal to `request.sh` alone, never to the CLI it started, so one trap is
the whole steer mechanism. The skeleton lets the current call finish, then runs the steer as the
next message. A CLI that reads stdin mid-turn can be handed the text at once instead.

A stop (`SIGTERM`) goes to `request.sh`'s whole process group; a kill follows after
`run.stop_timeout_s`.

## response.sh

Runs when `request.sh` has ended, however it ended, with everything above plus:

| Variable | Value |
|---|---|
| `HI_STDOUT`, `HI_STDERR` | paths to `request.sh`'s captured streams |
| `HI_EXIT` | `request.sh`'s exit code |
| `HI_OUTCOME` | `exited`, or `cancelled` when a stop ended `request.sh` |

What it prints is the response's one output message, byte for byte: prose, JSON, a report, the
last line, a file's contents. Its exit code is the status: 0 is `completed`, anything else
`failed` with its stderr as the error. It runs after a cancel too, within the stop's grace, so
the package decides what a cancelled turn returns.

```bash
#!/usr/bin/env bash
set -u
if [ "$HI_OUTCOME" = "cancelled" ]; then printf 'cancelled after %s lines\n' "$(wc -l < "$HI_STDOUT")"; exit 0; fi
grep '"type":"result"' "$HI_STDOUT" | tail -n 1 | jq -r .result    # Claude Code's final answer, out of its stream-json
exit "$HI_EXIT"
```

Without `response.sh` the response is `request.sh`'s stdout and exit code. The catalog's
packages ship that way, so their responses are the CLI's raw output; a fork adds a
`response.sh` to shape it. The raw streams stay in the record either way.

## Seeds

Files, copied through the platform's safe writer, never read. `org` seeds overwrite on every
turn, so a tenant's managed settings always win. `user` seeds land once per member, then belong
to the member. `project` seeds land when a session starts, only where the workspace has no such
file, so a request's files win over them.

## Upload

```bash
tar czf my-harness.tgz -C my-harness .
curl -s -X PUT https://hi.example.com/v1/harnesses/my-harness -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/x-tar' --data-binary @my-harness.tgz
```

A single top-level directory wrapping everything is stripped. The reply is the package's
configuration and its new version. A 400 names what is wrong.

## Prove it

```bash
python scripts/live.py --url https://hi.example.com --key $KEY --harness my-harness
```

Nine checks, the same ones the catalog passed: make a file and say done, recall it on the next
turn, the archive holds it, a turn streams, a steer is accepted and answered, a running turn
cancels, the trace records all of it, and a `store: false` request leaves nothing behind.

Next: [The catalog](catalog/index.md).
