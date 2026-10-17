# harness-interface

Providers, sandboxes and harnesses are resources you manage over an API. A harness is any CLI
you can run from a shell. You call it through the OpenAI Responses wire format, it runs in a
sandbox, its own output streams back, and the server keeps the record. The server has no code
for any particular harness, provider or sandbox: adding one is a PUT.

```
PUT /providers/deepseek      {url, key}                 where model calls go
PUT /sandboxes/python-dev    {dockerfile, egress}       where a harness runs   (a locked-down `default` is built in)
PUT /harnesses/claude-code   {provider, sandbox, run, scripts}   how one CLI is run and reported on
POST /responses              {model: "claude-code/deepseek-chat", input: "..."}   ──►  the CLI's output, then the record
```

## Start here

[docs/walkthrough.md](docs/walkthrough.md): install, add a provider, a sandbox and a harness,
make the first request, continue it. The whole thing is four PUTs and a POST.

```bash
pip install -e .
hi serve                       # http://127.0.0.1:8000, state under ./data; needs Docker and git
```

`hi pack <folder>` prints a harness folder (its `harness.yaml` plus every script beside it) as the
JSON the PUT takes. `hi serve --runtime local` runs harnesses on the host instead of in Docker,
for development and tests: no isolation and no egress rule, and every record says `runtime: local`.

## The three resources

**Provider**: where calls go and the key that unlocks them. The server never interprets either; the
harness decides which variables want them.

```json
{"name": "deepseek", "url": "https://api.deepseek.com/anthropic", "key": "sk-..."}
```

**Sandbox**: a Dockerfile, the hosts a run may reach besides its provider, and the container
runtime. `default` ships built in, cannot be changed or deleted, and is as closed as Docker
allows (below). Add one when a harness needs more, a package index say, and name it on the harness.

```json
{"name": "python-dev", "dockerfile": "FROM python:3.12 ...", "egress": ["pypi.org"], "runtime": "auto"}
```

**Harness**: everything needed to run one CLI, with its scripts inline, and by name the provider it
calls and the sandbox it runs in.

```yaml
name: claude-code
provider: anthropic          # any provider; the run script maps its url and key onto the CLI's variables
sandbox: default
files:
  AGENTS.md: "{instructions}"           # written into the workspace before the run
run:
  argv: [bash, "{harness_dir}/run.sh"]
  env: { HOME: "{workspace}/.home" }    # on top of the contract variables
  stdout: application/x-ndjson          # what the CLI prints; kept as the response's output
  timeout_s: 900
# scripts: {run.sh: ..., report.py: ...}  — `hi pack` adds the folder's files
```

Templates in `argv`, `env` and `files` take `{task}`, `{instructions}`, `{model}`,
`{session_id}`, `{workspace}`, `{harness_dir}`, `{provider_url}` and `{provider_key}`.

The keys never come back out: `GET /providers` returns names and urls only.

## The process contract

Inside the sandbox the harness's command gets:

| Input | Where |
|---|---|
| the request as JSON | stdin, and the file at `HI_REQUEST` |
| `HI_TASK`, `HI_MODEL`, `HI_SESSION_ID` | env; the session id is the harness's own resume handle from the previous response, or empty |
| `HI_PROVIDER_URL`, `HI_PROVIDER_KEY` | env; the harness's provider |
| `HI_WORKSPACE`, `HI_HARNESS_DIR`, `HI_OUTPUT` | env |
| the harness's `files:` and the request's input files | in the workspace |

And gives back:

| Output | Where |
|---|---|
| the response body | stdout, kept byte for byte at `GET /responses/{id}/output` |
| the log | stderr, at `GET /responses/{id}/log` |
| `status`, `session_id`, `usage`, `answer`, `cost_usd` | optional JSON written to `HI_OUTPUT` |
| produced files | whatever changed in the workspace, by git diff |

That is the whole interface between the server and a harness. Pointing Claude Code at DeepSeek
is one line in its run script, `ANTHROPIC_BASE_URL` from `HI_PROVIDER_URL` and the key, and
nothing in the server. The walkthrough has the complete Claude Code harness, three files, and
the lines that differ for Codex and DeepSeek Harness.

## Calling a harness

`POST /responses` takes the Responses request shape:

| Field | Here |
|---|---|
| `model` | the harness name, or `harness/model` to pass a model through as `HI_MODEL` |
| `input` | the task: a string, or `input_text` and `input_file` items; a file is written into the workspace |
| `instructions` | available to the harness's `files:` as `{instructions}` |
| `previous_response_id` | continue that conversation: its workspace, its harness, its resume handle |
| `stream` | server-sent events, else one JSON object |
| `metadata` | stored as given |

The record is a Response object: `id`, `status` (`completed`, `failed`, `incomplete` on timeout,
`cancelled`), `model`, `output` holding one assistant message with the harness's reported answer,
`usage` as the harness reported it, `previous_response_id`, `metadata`, and one extension key,
`harness`: name, provider, sandbox, runtime, image, workspace, session id, exit code, latency,
cost, produced files.

Streamed, it is SSE in the Responses framing: `response.created` first, one `harness.output`
event per line of the CLI's own stdout as it arrives, `response.completed` with the record last.
A Responses client sees a valid start and end and may ignore the middle; a client that knows the
CLI reads its events exactly as it printed them.

A conversation is a chain of responses. `previous_response_id` reuses that response's workspace,
with the files as the agent left them, and hands the CLI the session id it reported, so Claude
Code is resumed with `--resume`, Codex with `exec resume`, dsh with `--session-id`. A response
cannot continue one made on another harness.

## Endpoints

| Method | Path |
|---|---|
| PUT / GET / DELETE | `/providers/{name}`, `/sandboxes/{name}`, `/harnesses/{name}` |
| GET | `/providers`, `/sandboxes`, `/harnesses` |
| POST | `/responses` |
| GET | `/responses`, `/responses/{id}`, `/responses/{id}/output`, `/responses/{id}/log`, `/responses/{id}/files/{path}` |
| POST | `/responses/{id}/cancel` |

## The sandbox

Every response is one `docker run` of the image built from its sandbox's Dockerfile: the
workspace mounted at `/workspace`, the harness's scripts at `/harness` read-only, the request on
stdin, the contract variables and the harness's env inside. The image is built the first time a
Dockerfile with that content is seen and reused after; change the Dockerfile and the next
response builds and uses the new one, no restart. Every run gets, whatever its sandbox:

- all capabilities dropped, no privilege escalation, a read-only root filesystem, tmpfs `/tmp`,
  pid and memory caps;
- gVisor (`--runtime=runsc`) when the host has it, plain `runc` otherwise, `runtime: runc` or
  `runsc` on the sandbox to insist; the record says which ran;
- an internal Docker network of its own, with no route to the internet, the host, or other runs.
  Its only other member is the egress door.

The door is a CONNECT-only tunnel (`hi/egress.py`, sixty lines) whose allowlist is the host of the
harness's provider plus whatever the sandbox's `egress` names. It resolves names itself, so the
sandbox has no DNS; TLS stays end to end, so it sees nothing; everything that is not a tunnel to
an allowed host is a 403. The CLI reaches it through `HTTPS_PROXY`. A harness can call its model
and nothing else, and the door cannot be used for anything but that.

## Layout

```
hi/
  app.py        the routes: validate, call, shape
  models.py     Provider, Sandbox, Harness, the request, the Response record
  registry.py   the three resources; the built-in default sandbox; a harness's scripts on disk
  responses.py  one response end to end, and the wire format mapping in and out
  runner.py     the process contract: files, env, request.json, output.json
  sandbox.py    the Sandbox interface: Docker (image, network, door, run, kill) and subprocess
  egress.py     the door
  workspace.py  a conversation's directory, its git baseline, produced files by diff
  store.py      one JsonStore class for the four stores
  template.py   {a.b} placeholders
  cli.py        hi serve | hi pack
  default.Dockerfile
docs/           the walkthrough
tests/          every endpoint through an echo harness on the subprocess runtime; the door; the docker command lines
```

## Verified

Through this interface, with the real CLIs, each written as a harness the way the walkthrough
shows: Claude Code on Anthropic, Claude Code on DeepSeek's Anthropic-compatible endpoint with
`deepseek-chat`, Codex on OpenAI, DeepSeek Harness on DeepSeek, and the harness-engineering
course's own harness.py on Anthropic, each answering the same question; Claude Code on DeepSeek,
Codex and dsh each continued once with `previous_response_id` and recalled a word from the first
turn. The docker command lines, the image tagging and the door are covered by
tests; the live runs above used `--runtime local`, since the box they ran on has no Docker daemon.

## Trust

Single tenant. The API binds to localhost and has no authentication; keep it there. Provider keys
are stored as mode-600 files under `data/providers/` and enter a run only as environment
variables inside its container. A harness is code you chose to run; the sandbox limits what it can
reach, not what it can do to its own workspace.
