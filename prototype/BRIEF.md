# Rebuild prototype: the brief every agent follows

The owner asked for this work, and asked that each agent **write its own files** in this directory
(`R` below). Writing the files named here is the job, not a side effect.

`R` = `/tmp/claude-0/-home-user/37719b48-fc3a-58ba-bb72-5869c819d794/scratchpad/rebuild`

## What we are doing, and why

harness-interface runs coding-agent CLIs ("harnesses") behind one API, each run in a locked-down
container. We are rebuilding it from scratch (branch `v2`, later). **Before writing the server, we work
backwards from the harness folders**: build a template folder, rebuild five real harnesses from it,
and prove they run — locally, then sandboxed with a cached install and no key baked in — so that the
**minimal execution contract**, the **sandbox/install design** and **secret passing** are derived from
what real harnesses need, not guessed. Harnesses change fast; the contract must stay small and
generic enough for any harness, today's or a new kind.

Decided by the owner:
- **Sessions**, not runs. Interactivity degrades per harness: `run.interrupt` = `steered` (text goes
  into the work in progress), `continued` (stop gracefully, resume the CLI's conversation with the
  text), `responded` (stop, start again in the same workspace).
- **Cached install per harness version.** A minimal base image holds no CLIs and no secrets. A
  harness's `install.sh` runs once in an **install container** (egress only to its declared install
  hosts, **no secrets**) and fills a tools directory, cached by a hash of `install.sh` + the base
  image. Every session container mounts that directory **read-only** and may reach **only its
  provider** (through the egress door, a CONNECT-only allowlist proxy).
- **Providers per request**, with an API shape: `anthropic-messages` | `openai-responses` |
  `openai-chat`. A harness declares which shapes it speaks.
- **`home/`** in a harness folder (any tree of files) is copied into `$HOME` before every response;
  it replaces the old `artifacts` file.
- KISS, DRY, SRP, OOP where there is state, negative-space programming, test-driven.

First wave: **claude-code, codex, pi, opencode, hermes**.

## Contract hypothesis v0 (to prove, refine or cut)

Folder:
```
<name>/
  harness.json   name, description, provider (default), apis, sandbox, install{egress}, files, run{argv, env, stdout, timeout_s, interrupt}
  install.sh     installs the CLI (pinned) into $HI_TOOLS; executables end up in $HI_TOOLS/bin
  run.sh         maps HI_* onto the CLI's own settings, then execs the adapter
  adapter.py     drives the CLI (see below); stdlib python3 unless the CLI forces otherwise
  home/          optional: copied into $HOME before every response
```
A harness is given: env `HI_TASK`, `HI_MODEL`, `HI_RESUME`, `HI_PROVIDER_URL`, `HI_PROVIDER_API`, the
key (how is to be decided, see Secrets), `HI_WORKSPACE`, `HI_HARNESS_DIR`, `HI_TOOLS`, `HI_OUTPUT`,
`HI_REQUEST`; `PATH` starting with `$HI_TOOLS/bin`; `HOME=$HI_WORKSPACE/.home`; `NO_PROXY=127.0.0.1,localhost`;
`HTTPS_PROXY` = the egress door. stdin line 1 = the request as one compact JSON line
`{task, instructions, model, resume, files, metadata}`; for `steered`, stdin stays open and each later
line is one JSON string of new text; EOF = stop gracefully. SIGINT to the process group (tini with
process-group forwarding) = stop gracefully; a kill follows a timeout. It gives back: stdout and stderr
(streamed), workspace changes, and `$HI_OUTPUT` = `{answer, status: "ok"|"fail", resume, usage,
cost_usd, steers}` written **early** (as soon as the resume id is known) and **atomically** (tmp +
rename), rewritten at the end. Status comes from the CLI's events, never its exit code.

Adapter rules (from the survey, `R/../harness-survey/SUMMARY.md` §2–4): start the CLI and any daemons
in their **own session** (`start_new_session=True`) so our SIGINT reaches only the adapter, which then
uses the CLI's own graceful stop; a stdin thread turns each later line into the CLI's steer (or a new
prompt when idle); count steers; done = the pattern's condition with nothing queued; killpg children in
`finally`.

Secrets — options to test and choose between (the key must never be in an image layer, the tools
directory, a record or log, the workspace after the run, a host command line or `ps`, and ideally not
in `docker inspect`): (a) env var passed by name (`docker run -e NAME`, value only in the docker
client's environment); (b) a file on a host tmpfs (e.g. `/dev/shm/hi-<id>/key`, mode 0400, owner the
sandbox uid), bind-mounted read-only, path in `HI_PROVIDER_KEY_FILE`, deleted at teardown;
(c) anything better you find. Note what the CLI itself then does with it (some write it to disk).

## Shared rules for every agent

- **Never modify** `/home/user/harness-interface` or any git repository. You may read and import from it
  (e.g. `harness_interface.runtimes.egress.Door`, `runtimes.docker`, `runtimes.process`,
  `workspace.Workspace`) by putting it on `sys.path`.
- **Keys** are in `/home/user/harness-interface/data/secrets/{ANTHROPIC_API_KEY,OPENAI_API_KEY,DEEPSEEK_API_KEY}`.
  Load a key only into the process that needs it. Never print, echo, log or write it anywhere except
  the secret mechanism under test (and delete that). Never paste output that might contain it. To
  audit for leaks, grep for the key **without printing it** (e.g. `grep -rqF -f keyfile DIR && echo LEAK`).
- Strip inherited `CLAUDE*`, `CCR*`, `ANTHROPIC*`, `OPENAI*` variables from child environments;
  keep the machine's proxy/CA settings for host-side runs.
- Docker is running (start it with `nohup dockerd >/dev/null 2>&1 &` if `docker info` fails). Disk:
  ~15 GB free, shared; keep what you build lean and delete scratch you don't need. Never remove
  images or files another agent made.
- Models: Anthropic `claude-sonnet-4-6`; OpenAI `gpt-5-mini`; DeepSeek `deepseek-chat`.
- Use timeouts on everything. Be exact and terse in what you write.
- Prior knowledge to reuse: `R/../harness-survey/` (per-harness surveys + SUMMARY.md),
  `R/../validate/` (earlier driver scripts: codex app-server, claude stream-json, pi rpc, and the
  server validation of SIGINT through `docker --init -e TINI_KILL_PROCESS_GROUP=1`).

## Files

- `R/foundation/` — the template, base image, prototype runner, secrets experiment (stage 1).
- `R/harnesses/<name>/` — each rebuilt folder (stage 2).
- `R/reports/foundation.md`, `R/reports/<name>.md` — each agent's report (≤150 lines).
- `R/FINDINGS.md` — the consolidated result (stage 3).
