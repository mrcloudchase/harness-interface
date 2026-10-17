# harness-interface

Register harnesses as resources. Route requests to them. Pass the response through.

A harness here is any program you can start from a shell: Claude Code, Codex, pi, Hermes, a
script of your own. You describe it in a YAML resource, the server runs it under one fixed process
contract, and the bytes it prints are the response. The server has no code for any particular
harness. Adding one adds a folder, never a server change.

```
POST /runs {"task": "..."}  ──►  router picks a harness  ──►  spawn its command  ──►  stdout streams back
                                   (pinned, static, or Jev)      in a workspace          unchanged
```

New here? Read [docs/walkthrough.md](docs/walkthrough.md) first, then [docs/adding-a-harness.md](docs/adding-a-harness.md).

## Quick start

```bash
uv pip install -e .            # or: pip install -e .
hi serve                       # http://127.0.0.1:8000, data in ./data

# in another shell
hi secret ANTHROPIC_API_KEY    # reads $ANTHROPIC_API_KEY, or paste on stdin
hi apply harnesses/*/harness.yaml routes/static.yaml
hi run "What files are in this folder? Answer in one line." --harness claude-code
hi run "Fix the failing test" --file prices.py --file test_prices.py --check "python -m unittest -q"
```

`hi run` streams the harness's own output to stdout and prints the run record to stderr.

## The process contract

The server starts your `run.argv` in the session's workspace with:

| Input | Where |
|---|---|
| the whole request as JSON | stdin, and the file at `HI_REQUEST` |
| `HI_TASK`, `HI_MODEL`, `HI_SESSION_ID` | env (session id is the harness's own resume handle from the last run, or empty) |
| `HI_WORKSPACE`, `HI_HARNESS_DIR`, `HI_OUTPUT` | env |
| the secrets the resource names | env, by name |
| `files:` from the resource | written into the workspace, templated |

And takes back:

| Output | Where |
|---|---|
| response body | stdout, forwarded byte for byte with the resource's `run.stdout` content type |
| log | stderr, kept at `GET /runs/{id}/log` |
| `status`, `session_id`, `usage` | optional JSON written to `HI_OUTPUT` |
| produced files | whatever changed in the workspace, by git diff |
| status when no `HI_OUTPUT` | exit code zero is `ok` |

That is the whole interface. Anything a CLI emits that you want reshaped, reshape inside your own
command. See `harnesses/claude-code/report.py` for the pattern: pass lines through, write the
three fields the server reads.

## A harness resource

```yaml
kind: Harness
name: claude-code
description: >            # the routing prompt: what Jev reads when choosing this harness
  Anthropic's Claude Code CLI, headless. ...
labels: [coding, shell]
models: [claude-sonnet-5-5]
secrets: [ANTHROPIC_API_KEY]
files:
  AGENTS.md: "{request.instructions}"
run:
  argv: [bash, "{harness_dir}/run.sh"]
  env: { HOME: "{workspace}/.home" }
  stdout: application/x-ndjson
  timeout_s: 900
check: [claude, --version]   # readiness probe, run at apply time
```

Templates take `{request.*}`, `{workspace}`, `{harness_dir}` and `{session.*}`.
`hi apply` sets `{harness_dir}` to the YAML's folder, so a resource is a folder you can version.

## The route resource

A request that names no `harness` and no `session` is routed. The decision is authored in Jev's
own question types; the server resolves `from_registry`, renders `state`, makes one call, and
walks `decide` top to bottom.

```yaml
kind: Route
engine: jev                  # or static
model: jev-latest
state:
  task: "{request.task}"
questions:
  harness: {type: choice, instructions: Which registered harness should run this task?, criteria: from_registry}
  risky:   {type: noul,   instructions: Could this task change anything outside its workspace?}
  size:    {type: score,  instructions: How much work is this?, criteria: [one line, one file, several files, a project]}
decide:
  - when: risky.probability > 0.8
    then: reject needs a person
  - when: harness.confidence >= 0.6
    then: use harness.choice
  - then: use default
default: claude-code
```

Answers are flattened for the rules: a choice gives `choice`, `confidence`, `runner_up`; a noul
gives `probability`; a score gives `score`, `level`, `confidence`. The `jev` engine needs the
`TYPESAFE_API_KEY` secret. Routing happens once, when a session is created; a follow-up with
`session` always runs on the harness that started it.

## API

| Method | Path | Purpose |
|---|---|---|
| PUT | `/harnesses/{name}` | apply a Harness (validates, runs `check`, bumps version) |
| GET / DELETE | `/harnesses[/{name}]` | list, read, remove |
| PUT / GET | `/route` | apply or read the Route |
| PUT / GET | `/secrets[/{name}]` | store a value (body), list names |
| POST | `/runs` | run a task; streams the body, or `{"stream": false}` for JSON |
| GET | `/runs`, `/runs/{id}`, `/runs/{id}/log`, `/runs/{id}/files/{path}` | records, log, produced files |
| POST | `/runs/{id}/cancel` | kill the process |
| GET | `/sessions[/{id}]` | workspaces and resume handles |

Run request fields: `task`, `instructions`, `model`, `harness`, `session`, `files[{name,content}]`,
`check` (a shell command run in the workspace afterwards; exit zero means pass), `stream`.
Every `POST /runs` answers with `X-Run-Id`, `X-Session-Id` and `X-Harness` headers.

## Layout

```
hi/
  app.py        HTTP routes, thin
  service.py    one request end to end: decide, prepare, run, record
  runner.py     the process contract: prepare env and files, spawn, stream, kill at the cap
  workspace.py  a session's directory and its git baseline
  registry.py   Harness and Route resources: validate, probe, version
  router/       Router protocol; static and Jev engines; the decide-rule evaluator
  models.py     the schemas: what you author, and what the server stamps on it
  template.py   {a.b.c} placeholders
  storage.py    JSON files and secrets; swap for a database here
  cli.py        hi serve | apply | secret | run | get
harnesses/      resources: one folder each (claude-code, codex, deepseek-harness, echo)
routes/         static.yaml and jev.yaml
tests/          unit tests, and the whole path through the echo harness
```

## Verified

Through this interface, on the shop task from the harness-engineering repo ("The tests are failing.
Find out why and fix it." with `check: python3 -m unittest -q`):

| Harness | Result | Follow-up on the same session |
|---|---|---|
| claude-code | fixed, check passed, ~10 s | resumed its own session and recalled the change |
| deepseek-harness | fixed, check passed, ~14 s | resumed its own session and recalled the change |
| codex | fixed, check passed, ~17 s | resumed its own session and recalled the change |

The `jev` route was exercised live with `TYPESAFE_API_KEY`: Jev returned a probability per registered
harness, a risk probability and a size level, and the decide table fell through to `default` when the
choice confidence was under the threshold. Set the threshold from your own run history, not by feel.

## Trust

Single tenant. The box is the trust boundary: secrets go into the harness process's environment,
and every harness runs with its own approvals off. Do not expose the port beyond localhost.
Secrets are stored as mode-600 files under `data/secrets/`; the server's own environment is the fallback.
A harness process inherits the server's environment, with the resource's `env` and the contract variables on top,
so start `hi serve` with the environment you want every harness to see and nothing more.
