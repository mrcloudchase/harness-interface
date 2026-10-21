# The harness template

A harness is a folder you upload. The server reads three things from it and copies the rest:

```
my-harness/
  harness.json      what the server needs to launch it: defaults, variable names, the steer signal, caps
  install.sh        puts the CLI into $HI_TOOLS, once per sandbox image
  request.sh        runs one turn: the prompt on stdin, its stdout and stderr the response
  seeds/org/        copied into $HOME on every turn, overwriting (the org's managed settings)
  seeds/user/       copied into $HOME on a member's first use only (a starting point that becomes theirs)
  seeds/project/    copied into the workspace when a session starts, only where no file exists (the repo wins)
```

Nothing else is required and nothing else is read. Two harnesses with the same CLI and different
seeds or flags are two folders under two names: `claude-code-app1`, `claude-code-devteam`,
`codex-marketing`. A program you wrote yourself is a folder whose `request.sh` runs it.

Upload with `tar czf my-harness.tgz -C my-harness .` and `PUT /v1/harnesses/my-harness` with the
archive as the body. The server checks the three files are there and the scripts parse, stores the
folder by the digest of its bytes, and makes it the current version. A session keeps the version it
started on; re-upload the previous folder to roll back.

## harness.json

```json
{
  "contract": 3,
  "description": "Claude Code, headless, for the dev team",
  "defaults": {"sandbox": "node22", "provider": "anthropic", "model": "your-model-id"},
  "provider_env": {"key": "ANTHROPIC_API_KEY", "url": "ANTHROPIC_BASE_URL"},
  "interrupt": "SIGUSR1",
  "install": {"egress": ["registry.npmjs.org"], "timeout_s": 900},
  "run": {"timeout_s": 3600, "stop_timeout_s": 20}
}
```

| Key | Meaning |
|---|---|
| `defaults` | The sandbox, provider and model a request with a bare harness name uses; a request's `model` of `sandbox/harness/provider/model` names its own. The model is whatever id the provider serves (`deepseek-chat` on DeepSeek's Anthropic-compatible endpoint, for instance). Any may be empty; a request must then name it. |
| `provider_env` | Variable names to put the session token and the gateway URL in, so the CLI finds its credential where it looks. Optional: `HI_PROVIDER_KEY_FILE` and `HI_PROVIDER_URL` are always set. |
| `interrupt` | The signal a steer sends after writing `$HI_DIR/interrupt`: `SIGUSR1`, `SIGUSR2`, `SIGINT`, `SIGTERM` or `SIGHUP`. |
| `install.egress` | Hosts `install.sh` may reach. `install.timeout_s`: its cap. |
| `run.timeout_s` | A turn's wall-clock cap; past it the turn is `incomplete`. `run.stop_timeout_s`: how long a cancel waits after SIGTERM before SIGKILL. |

Unknown keys are refused by name.

## install.sh

Runs once per (harness version, sandbox image), as root in the sandbox image, with `$HI_TOOLS`
writable and `$HI_HARNESS_DIR` the folder. Put the CLI under `$HI_TOOLS`; `$HI_TOOLS/bin` is on
`PATH` at run time. Pin the version.

```bash
#!/usr/bin/env bash
set -euo pipefail
VERSION=2.1.305
mkdir -p "$HI_TOOLS/bin"
npm install --global --prefix "$HI_TOOLS" --no-audit --no-fund "@anthropic-ai/claude-code@$VERSION"
"$HI_TOOLS/bin/claude" --version
```

## request.sh

Runs once per turn, in the sandbox, as an unprivileged user, in the session's workspace, with:

| Variable | Value |
|---|---|
| stdin | the prompt: the request's text. Its files are already in the workspace. |
| `HI_WORKSPACE` | the working directory, kept between turns of a stored session |
| `HOME` | the member's home for this harness, seeded, kept between sessions |
| `HI_DIR` | a run directory: `$HI_DIR/interrupt` is the steer's text when one arrives |
| `HI_SESSION`, `HI_RESPONSE` | the session's and the response's ids |
| `HI_TURN` | 1 for a session's first turn, then 2, 3… so the script knows to resume |
| `HI_MODEL` | the model to use |
| `HI_INSTRUCTIONS` | the request's `instructions`, if any |
| `HI_PROVIDER_URL`, `HI_PROVIDER_KEY_FILE` | the gateway's URL and a file holding the session token; plus `provider_env`'s names set to the same |
| `HI_HARNESS_DIR`, `HI_TOOLS`, `PATH` | the folder, the tools layer, `$HI_TOOLS/bin` first |

Everything it writes to stdout is the response's first message, stderr the second, its exit code
the status: 0 is `completed`, anything else `failed`. Nothing is parsed. Choose the CLI's output
mode in the script: JSON lines for a program to read, prose for a person.

### Verified harnesses

Each page below is a complete folder, proven with `scripts/live.py` against a running server on the
sandbox and provider named, with the checks it passed: **make** a file and say done, **recall** it on the
next turn of the same session, **archive** holds the file, **stream** a turn's output, a **steer** is
accepted mid-turn and answered, a running turn **cancels**, the **trace** records all of it, and a
`store: false` request leaves nothing behind (**stateless**). Copy the folder, change the version pin or
the seeds, upload it under your own name.

<!-- harness-table -->
| Harness | Sandbox | Provider | Checks | Note |
|---|---|---|---|---|
| [pi](harnesses/add-pi.md) | `node22` | `deepseek` (Anthropic Messages) | 0/9 |  |
| [Hermes Agent](harnesses/add-hermes.md) | `full` | `deepseek` (Anthropic Messages) | 0/9 |  |
| [Codex](harnesses/add-codex.md) | `node22` | `openai-responses` (OpenAI Responses) | 0/9 |  |

Not on the list, and why:

- **Gemini CLI**: speaks only Google's Gemini API; neither OpenAI nor DeepSeek serves it.
- **Qoder CLI**: runs on Qoder's cloud and needs a Qoder account; the provider is not yours to choose.
- **SystemOne**: needs a TypeSafe decision-model provider beside the coding model.
- **Agent Zero**: has no command line; the reference drives it in-process with a Python driver, which is a harness of its own.
<!-- /harness-table -->

Every `request.sh` on those pages shares one skeleton: the prompt from stdin, `cd "$HI_WORKSPACE"`,
`set -m` so each turn runs in its own process group (the steer signal then reaches the script, not the
CLI, whose own handler for it might start a debugger or exit), a `run_wait` that runs the turn and
waits through signals, passing a stop on to it, and a USR1 trap that reads `$HI_DIR/interrupt`. The
CLI-specific part is a `turn` function; the tail runs the prompt and then, if a steer arrived, the
steer as the next turn of the same conversation. A steer is therefore delivered after the running
turn ends; a CLI that reads stdin mid-turn could be handed it at once instead.

### Example: a script harness

Not every harness is a coding agent. This one runs the workspace's own check and reports; a loop
uses it to judge another harness's work. No provider is contacted, so any provider name will do.

```json
{"contract": 3, "description": "runs ./check.sh in the workspace", "defaults": {"sandbox": "py312", "provider": "none"},
 "install": {"egress": []}, "run": {"timeout_s": 600}}
```

```bash
#!/usr/bin/env bash
# install.sh: nothing to install
exit 0
```

```bash
#!/usr/bin/env bash
# request.sh: the prompt names the script, or ./check.sh by default
set -u
script=$(cat); script=${script:-./check.sh}
[ -x "$script" ] || { echo "no $script" >&2; exit 2; }
"$script"
```

## Steer, cancel and timeout

A steer (`POST /v1/sessions/{id}/interrupt`) writes its text to `$HI_DIR/interrupt`, then sends
`interrupt`'s signal to `request.sh`'s process group. What that means is the script's: forward it,
read the file at the next step, or ignore it. A cancel (`POST /v1/responses/{id}/cancel`) is
SIGTERM to the group, then SIGKILL after `stop_timeout_s`; the status is `cancelled` and the output
so far is kept. Past `run.timeout_s` the turn is killed and `incomplete`. In every case the
workspace and `$HOME` stay as they were left, so the next turn continues from there.

## Checking a folder before upload

`PUT /v1/harnesses/{name}` answers 400 naming what is wrong: a missing file, a script that does not
parse, an unknown key in `harness.json`, a seeds directory that is not `org`, `user` or `project`.
The first request then runs `install.sh`; its failure is that response's `error`, with the log's
tail.
