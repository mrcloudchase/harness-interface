# Harness packages

A harness package is a folder a tenant owns. The platform reads three things from it, runs two, and
copies the rest; it never reads what the scripts print.

```
<name>/
  harness.json      what the platform needs to launch it: defaults, variable names, the signal, egress, timeouts
  install.sh        puts the CLI into $HI_TOOLS, once per package version, unprivileged, in the base image
  request.sh        runs one turn: the prompt on stdin, stdout relayed live, both streams kept
  response.sh       optional: decides what the response carries, from request.sh's streams and exit code
  seeds/org/        copied into $HOME on every turn, overwriting (managed settings)
  seeds/user/       copied into $HOME on a member's first use only (a starting point that becomes theirs)
  seeds/project/    copied into the workspace when a session starts, only where no file exists
```

Upload with `tar czf <name>.tgz -C <name> .` and `PUT /v1/harnesses/<name>` with the archive as
the body, or fork a catalog package with `{"catalog": "<package>"}` as a JSON body. The platform
validates the folder (the three required files, the scripts parse, the egress hosts are public,
`harness.json` has no unknown keys), stores it by the digest of its bytes, and makes it the current
version. A session keeps the version it started on; re-upload an older folder to roll back.

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
| `run.timeout_s` | A turn's wall-clock cap, within the tenant's ceiling; past it the turn is `incomplete`. `run.stop_timeout_s`: how long a cancel waits after SIGTERM before SIGKILL. |

Unknown keys are refused by name.

## The sandbox a turn runs in

The platform's base image (Debian, Python 3.12, Node 22, git, curl, ripgrep, procps, tmux), a fresh
container per turn, the tenant's own unprivileged user, no capabilities, a read-only root with a
writable `/tmp`, the tenant's cpu, memory and pid ceilings, and one route out: a door that tunnels
to `run.egress` and forwards provider calls to the gateway. Tenants choose none of this.

## What request.sh gets

| Variable | Value |
|---|---|
| stdin | the prompt: the request's text. Its files are already in the workspace. |
| `HI_WORKSPACE` | the working directory, kept between turns of a stored session |
| `HOME` | the member's home for this package, seeded, kept between sessions |
| `HI_DIR` | a run directory: `$HI_DIR/interrupt` is the steer's text when one arrives; `$HI_DIR/prompt` the prompt |
| `HI_REQUEST` | the request body, as sent, as a JSON file: every field, present or future |
| `HI_SESSION`, `HI_RESPONSE` | the session's and the response's ids |
| `HI_TURN` | 1 for a session's first turn, then 2, 3… so the script knows to resume |
| `HI_MODEL` | the model to use |
| `HI_INSTRUCTIONS` | the request's `instructions`, if any |
| `HI_PROVIDER_URL`, `HI_PROVIDER_KEY_FILE` | the gateway's URL (with the provider's path) and a file holding the session token; plus `provider_env`'s names set to the same |
| `HI_HARNESS_DIR`, `HI_TOOLS`, `PATH` | the package, the tools layer, `$HI_TOOLS/bin` first |

Its stdout is relayed live to a streaming client and kept; its stderr is kept; its exit code is
kept. A steer delivers `interrupt`'s signal to `request.sh` alone, never to the CLI it started, so one
trap in the script is the whole steer mechanism. A stop (SIGTERM) goes to its whole process group.

## What response.sh decides

It runs when `request.sh` has ended, however it ended, with everything above plus:

| Variable | Value |
|---|---|
| `HI_STDOUT`, `HI_STDERR` | paths to `request.sh`'s captured streams |
| `HI_EXIT` | `request.sh`'s exit code |
| `HI_OUTCOME` | `exited`, or `cancelled` when a stop ended `request.sh` |

What it prints to stdout is the response's one output message, byte for byte: prose, JSON, a report,
the last line, a file's contents. Its exit code is the status: 0 is `completed`, anything else
`failed` with its stderr as the error. It runs even after a cancel, within the stop's grace, so the
package decides what a cancelled turn returns. A package without `response.sh` returns
`request.sh`'s stdout and exit code; a turn that ran past its timeout returns what was captured.

The raw streams stay in the record either way (`GET /v1/responses/{id}?detail=true` and the trace),
so a package shapes the response without hiding what happened.

## A worked request.sh

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

A steer becomes the next message once the current turn ends; a CLI that reads stdin mid-turn could
be handed it at once instead. `catalog/template/` is the smallest complete package to start from,
with a `response.sh` that returns the CLI's last line.

## Verified packages

Every package in the catalog was run through `scripts/live.py` against a running platform: make a
file and say done, recall it on the next turn, the archive holds it, a turn streams, a steer is
accepted and answered, a running turn cancels, the trace records all of it, and a `store: false`
request leaves nothing behind. [The catalog pages](harnesses/) show each package's folder, the checks
it passed and its caveats.
