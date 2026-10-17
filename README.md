# harness-interface

Register harnesses as resources. Hand every one of them the same task. Keep score.

A harness here is any program you can start from a shell: Claude Code, Codex, pi, Hermes, a
script of your own. You describe it in a YAML resource, the server runs it under one fixed process
contract, and the bytes it prints are the response. The server has no code for any particular
harness. Adding one adds a folder, never a server change.

A request is served one of three ways:

| Mode | What happens | What it changes on the cards |
|---|---|---|
| `fanout` (default) | every registered harness runs the task at once; the judge labels each output; the referee picks the winner among the delivered ones | a win for the winner, a loss for every other entrant, a verdict per run |
| `route` | the route picks one harness from the cards: each one's name and record, nothing else | a verdict for that run; never a win or loss |
| `named` | the harness in the request, or the session's | a verdict for that run; never a win or loss |

```
POST /runs {"task": "..."}  ──►  fanout: every harness runs  ──►  judge labels each  ──►  referee picks the winner
                            ──►  route:  Jev picks one from the records  ──►  it runs  ──►  judge labels it
                            ──►  named:  that harness runs  ──►  judge labels it
```

Wins and losses come only from contests, where every harness faced the same task at the same
time. A routed run earns nothing, so the route cannot feed the harness it favors.

New here? Read [docs/walkthrough.md](docs/walkthrough.md) first, then [docs/adding-a-harness.md](docs/adding-a-harness.md).

## Quick start

```bash
uv pip install -e .            # or: pip install -e .
hi serve                       # http://127.0.0.1:8000, data in ./data, the console at /ui

# in another shell
hi secret ANTHROPIC_API_KEY    # reads $ANTHROPIC_API_KEY, or paste on stdin
hi secret TYPESAFE_API_KEY     # the judge and the referee
hi apply harnesses/*/harness.yaml routes/jev.yaml
hi run "What files are in this folder? Answer in one line." --harness claude-code
hi run "Fix the failing test" --file prices.py --file test_prices.py        # fan-out: everyone runs, one wins
hi run "Fix the failing test" --file prices.py --file test_prices.py --mode route
```

`hi run` streams what comes back to stdout, the harness's own output or, for a fan-out, NDJSON
lines tagged by harness, and prints the run or contest record to stderr.

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
| `status`, `session_id`, `usage`, `answer`, `cost_usd` | optional JSON written to `HI_OUTPUT` |
| produced files | whatever changed in the workspace, by git diff |
| status when no `HI_OUTPUT` | exit code zero is `ok` |

That is the whole interface. Anything a CLI emits that you want reshaped, reshape inside your own
command. See `harnesses/claude-code/report.py` for the pattern: pass lines through, write the
fields the server reads.

## A harness resource

```yaml
kind: Harness
name: claude-code
description: >            # for people reading the cards; Jev never sees it
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

One YAML holds the policy: how `route` mode picks a harness, how every run is judged, and how a
contest is won. All three are authored in Jev's own question types; the server resolves
`from_registry`, renders `state`, makes one call per decision, and walks `decide` top to bottom.

```yaml
kind: Route
engine: jev                  # or static: route mode always picks `default`
model: jev-latest
state:
  task: "{request.task}"
questions:
  harness: {type: choice, instructions: Which harness should run this task?, criteria: from_registry}
  risky:   {type: noul,   instructions: Could this task change anything outside its workspace?}
  size:    {type: score,  instructions: How much work is this?, criteria: [one line, one file, several files, a project]}
decide:
  - when: risky.probability > 0.8
    then: reject needs a person
  - when: harness.confidence >= 0.6
    then: use harness.choice
  - then: use default
default: claude-code
judge:                       # every run's verdict
  questions:
    completed: {type: noul, instructions: Was the task completed as asked?}
  success_when: completed.probability >= 0.5
arena:                       # how a contest is settled
  instructions: Which output best accomplishes the task?
```

`criteria: from_registry` makes one option per registered harness, and that option is the
harness's name and its record sentence: `12 runs: 9 delivered, 3 failed (75%). 4 contests: 3 won,
1 lost.` Nothing else. Descriptions are for people. Answers are flattened for the rules: a choice
gives `choice`, `confidence`, `runner_up`; a noul gives `probability`; a score gives `score`,
`level`, `confidence`. `POST /route/preview` shows the decision and the verbatim Jev request for
a task without running anything.

Routing happens once, when a session is created; a follow-up with `session` always runs on the
harness that started it. The `jev` engine, the judge and the referee all need the
`TYPESAFE_API_KEY` secret.

## Contests, verdicts and the record

A `fanout` request is a contest. Every registered harness gets the task in its own workspace and
session, concurrently. When all have finished, the contest is settled: one deliverer wins
outright; several go to the referee, which reads the task and each delivered output (the answer
and the produced files, under the harness's name only) and chooses; none means no winner and a
loss for everyone. If the referee itself fails, the contest is `void` and counts for nothing. The
contest record names the winner and the winner's session, so a follow-up continues the winning
harness.

Every finished run gets one label, its `verdict`: did it deliver the task.

1. **status** (`by: status`): the harness itself failed, timed out or was cancelled.
2. **judge** (`by: jev`): the route's `judge` asked Jev. It reads the task, the instructions, the
   harness's `answer` (reported through `HI_OUTPUT`, else the tail of its stdout) and the produced
   files, and `success_when` over its answers decides. It cannot run code or check facts.
3. **a person** (`by: human`): `PATCH /runs/{id}` or `hi verdict <run> pass|fail --note "..."` replaces either.

`GET /cards` is each harness with its record: runs, delivered, failed, contests, won, lost, plus
median latency, median cost where the harness reports one, and the median of every usage figure
it reports under its own names. Nothing is renamed or converted between harnesses: Claude Code's
`cache_read_input_tokens` and Codex's `cached_input_tokens` sit side by side as they are. The
record sentence is what the route sends to Jev; the rest is for people and the console.

## API

| Method | Path | Purpose |
|---|---|---|
| PUT | `/harnesses/{name}` | apply a Harness (validates, runs `check`, bumps version) |
| GET / DELETE | `/harnesses[/{name}]` | list, read, remove |
| PUT / GET | `/route` | apply or read the Route |
| POST | `/route/preview` | dry run of route mode: the decision and the verbatim Jev request, without running |
| GET | `/ui` | the console (`/` redirects here) |
| PUT / GET | `/secrets[/{name}]` | store a value (body), list names |
| POST | `/runs` | serve a task in its `mode`; streams the body, or `{"stream": false}` for JSON |
| GET | `/runs`, `/runs/{id}`, `/runs/{id}/output`, `/runs/{id}/log`, `/runs/{id}/files/{path}` | records, the harness's stdout, its stderr, produced files |
| PATCH | `/runs/{id}` | a person's verdict: `{"success": true, "note": "..."}` |
| POST | `/runs/{id}/cancel` | kill the process |
| GET | `/contests[/{id}]` | fan-out records: entrants, winner, the winner's session |
| GET | `/cards` | each harness with its record |
| GET | `/sessions[/{id}]` | workspaces and resume handles |

Run request fields: `task`, `instructions`, `model`, `mode` (`fanout`, `route`, `named`; left out,
`named` when a `harness` or `session` is given, else `fanout`), `harness`, `session`,
`files[{name,content}]`, `stream`.

A `named` or `route` request answers with the harness's stdout in the content type its resource
declared, and `X-Run-Id`, `X-Session-Id`, `X-Harness` headers. A `fanout` request answers with
`X-Contest-Id` and NDJSON: one `{"harness": ..., "line": ...}` per line of output from any
entrant as it arrives, then `{"contest": ...}` once settled. With `"stream": false` it is one
JSON object, `{"contest": ..., "runs": {name: run}}`.

## Layout

```
hi/
  app.py        HTTP routes, thin
  service.py    one run end to end: decide the harness, prepare, run, record, judge
  arena.py      fan-out: every harness at once, the merged stream, the referee, the contest record
  evidence.py   the record per harness from the run log and the contest log
  runner.py     the process contract: prepare env and files, spawn, stream, kill at the cap
  workspace.py  a session's directory and its git baseline
  registry.py   Harness and Route resources: validate, probe, version
  router/       Router protocol; static and Jev engines; the judge; the referee; the decide-rule evaluator
  models.py     the schemas: what you author, and what the server stamps on it
  template.py   {a.b.c} placeholders
  storage.py    JSON files and secrets; swap for a database here
  cli.py        hi serve | apply | secret | run | verdict | get
  ui/index.html the console: one static page over the API, no build step
harnesses/      resources: one folder each (claude-code, codex, deepseek-harness, harness-engineering, echo)
routes/         static.yaml and jev.yaml
tests/          unit tests, and the whole path through the echo harness, contests included
```

## Verified

Through this interface, live, with four real harnesses registered: a fan-out on the shop task from
the harness-engineering repo ("The tests are failing. Find out why and fix it.") ran all four at
once, the judge labeled every output, the referee picked a winner, and the cards carried the win
and the losses. `route` mode then picked a harness from the records alone; the verbatim Jev
request is visible through `POST /route/preview`. Each harness resumes its own session on a
follow-up.

## Trust

Single tenant. The box is the trust boundary: secrets go into the harness process's environment,
and every harness runs with its own approvals off. Do not expose the port beyond localhost.
Secrets are stored as mode-600 files under `data/secrets/`; the server's own environment is the fallback.
A harness process inherits the server's environment, with the resource's `env` and the contract variables on top,
so start `hi serve` with the environment you want every harness to see and nothing more.
