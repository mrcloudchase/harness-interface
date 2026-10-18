# Reference

Everything the server does, precisely. For the guided version see [walkthrough.md](walkthrough.md).

## Running the server

```bash
uv run harness-interface               # the entry point: harness_interface.app:main
uv run --extra dev pytest              # the tests; they need no Docker and no keys
```

| Variable | Default | Meaning |
|---|---|---|
| `HI_HOST` | `127.0.0.1` | the address to listen on |
| `HI_PORT` | `8000` | the port |
| `HI_DATA_DIR` | `./data` | resources, records, logs and workspaces |
| `HI_RUNTIME` | `docker` | where harnesses run: `docker`, or `local` for plain processes on the host |

## The three resources

Each is added with `PUT /<kind>/{name}`; the name in the path must match the `name` in the body.
A PUT replaces what was there and takes effect on the next request.

**Provider**: where model calls go and the key that unlocks them. The server never interprets
either. The harness decides which of its CLI's variables get them. The url's host and port (443
for `https`, 80 for `http`, unless given) are what the egress door lets through.

```json
{"name": "deepseek", "url": "https://api.deepseek.com/anthropic", "key": "sk-..."}
```

**Sandbox**: a Dockerfile, plus the hosts a run may reach besides its provider. `egress` entries
can be written three ways:
- `host`, which means port 443;
- `host:port`;
- a URL.

`default` is built in. It cannot be replaced or deleted. Its Dockerfile is
`harness_interface/default.Dockerfile`: the CLI of every harness in `harnesses/`, run as an
unprivileged user, uid 1000. A sandbox you add needs a user with uid 1000, because the workspace
is handed to that uid.

```json
{"name": "python-dev", "dockerfile": "FROM python:3.12-slim\n...", "egress": ["pypi.org"]}
```

**Harness**: everything needed to run one CLI. Its scripts are included inline, and it names the
provider it calls and the sandbox it runs in.

```json
{
  "name": "claude-code",
  "description": "...",
  "provider": "anthropic",
  "sandbox": "default",
  "files": {"AGENTS.md": "{instructions}"},
  "run": {
    "argv": ["bash", "{harness_dir}/run.sh"],
    "env": {"HOME": "{workspace}/.home"},
    "stdout": "application/x-ndjson",
    "timeout_s": 900
  },
  "scripts": {"run.sh": "...", "report.py": "..."}
}
```

| Field | Default | Meaning |
|---|---|---|
| `provider` | required | any provider; the run script maps its url and key onto the CLI's variables |
| `sandbox` | `default` | the sandbox it runs in |
| `files` | `{}` | path → content, written into the workspace before each run; both are templated |
| `run.argv` | `["bash", "{harness_dir}/run.sh"]` | the command, templated |
| `run.env` | `{}` | extra variables, templated, set alongside the contract's |
| `run.stdout` | `application/x-ndjson` | the content type of what the CLI prints, served at `/output` |
| `run.timeout_s` | `900` | the run is killed after this and recorded `incomplete` |
| `scripts` | `{}` | filename → content; stored under `data/scripts/{name}/` and mounted read-only at `{harness_dir}`; names must be plain filenames |

Templates take `{task}`, `{instructions}`, `{model}`, `{session_id}`, `{workspace}`,
`{harness_dir}`, `{provider_url}` and `{provider_key}`.
- Only `{identifier}` is a placeholder, so JSON or code braces in a file pass through untouched.
- An unknown placeholder fails the request with a 400.
- `{workspace}` and `{harness_dir}` are the paths as the harness sees them: `/workspace` and `/harness` in Docker.

## The process contract

Inside the sandbox, the harness's command gets:

| Input | Where |
|---|---|
| the request as JSON (`task`, `instructions`, `model`, `files`, `session_id`, `metadata`) | stdin, and the file at `HI_REQUEST` |
| `HI_TASK`, `HI_MODEL`, `HI_SESSION_ID` | env; the session id is the resume handle the previous response reported, or empty |
| `HI_PROVIDER_URL`, `HI_PROVIDER_KEY` | env; the harness's provider |
| `HI_WORKSPACE`, `HI_HARNESS_DIR`, `HI_OUTPUT` | env |
| `HTTPS_PROXY`, `HTTP_PROXY` | env, in Docker; the egress door |
| the harness's `files` and the request's input files | in the workspace, which is the working directory |

And gives back:

| Output | Where |
|---|---|
| the response body | stdout, kept byte for byte at `GET /responses/{id}/output` |
| the log | stderr, at `GET /responses/{id}/log` |
| `status`, `session_id`, `usage`, `answer`, `cost_usd` | optional JSON written to `HI_OUTPUT` |
| produced files | whatever it added or changed in the workspace, found by git |

`status` is `ok` or `fail`. Without it, an exit code of zero means `ok`. If a follow-up reports no
`session_id`, the previous one is kept. Nothing under `.hi/`, `.home/`, `.git/` or `__pycache__/`
is ever counted as a produced file, so a CLI's own state belongs in `.home/` (set `HOME` there).
That is the whole interface between the server and a harness.

## Calling a harness

`POST /responses` takes the Responses request shape:

| Field | Here |
|---|---|
| `model` | the harness name, or `harness/model` to pass a model through as `HI_MODEL` |
| `input` | the task: a string, or `input_text` and `input_file` items; each file is written into the workspace |
| `instructions` | available to the harness's `files` as `{instructions}` |
| `previous_response_id` | continue that conversation: its workspace, its harness, its resume handle |
| `stream` | server-sent events; otherwise one JSON object when the run is done |
| `metadata` | stored as given |

The record is a Response object:
- `id`;
- `status`: `completed`, `failed`, `incomplete` on timeout, or `cancelled`;
- `model`;
- `output`: one assistant message holding the harness's reported answer;
- `usage`, as the harness reported it;
- `previous_response_id` and `metadata`;
- `error` and `incomplete_details`;
- one extension key, `harness`, holding:
  - name, provider and sandbox;
  - runtime and image;
  - workspace and session id;
  - exit code, latency and cost;
  - produced files.

Streamed, the record arrives as SSE in the Responses framing:
1. `response.created`;
2. one `harness.output` event, `{"line": ...}`, for each line of the CLI's stdout as it arrives;
3. `response.completed`, carrying the record.

A Responses client sees a valid start and end and can ignore the middle. A client that knows the
CLI reads its events exactly as printed. If the client disconnects, the run still finishes and is
recorded.

A conversation is a chain of responses. A follow-up:
- reuses its predecessor's workspace, with the files as the harness left them;
- hands the CLI the session id it reported.

So Claude Code resumes with `--resume`, Codex with `exec resume` and Cline by loading its ACP
session. A response cannot continue one made on another harness.

## Endpoints

| Method | Path | |
|---|---|---|
| PUT | `/providers/{name}`, `/sandboxes/{name}`, `/harnesses/{name}` | add or replace |
| GET | `/providers`, `/sandboxes`, `/harnesses` | list; providers without keys; sandboxes with `default` first |
| GET | `/providers/{name}`, `/sandboxes/{name}`, `/harnesses/{name}` | one |
| DELETE | `/providers/{name}`, `/sandboxes/{name}`, `/harnesses/{name}` | `{"deleted": true\|false}` |
| POST | `/responses` | run a harness |
| GET | `/responses`, `/responses/{id}` | records |
| GET | `/responses/{id}/output`, `/responses/{id}/log` | stdout, stderr |
| GET | `/responses/{id}/files/{path}` | a file in the response's workspace |
| POST | `/responses/{id}/cancel` | `{"cancelled": true\|false}` |

Errors:
- 400 covers:
  - a path name that differs from the body's name;
  - an unknown harness, provider, sandbox or previous response;
  - a follow-up on another harness;
  - a bad script name or template;
  - writing or deleting `default`.
- 422 means the request body does not fit its shape, for example an `input` with no text.
- 500 means a sandbox image failed to build, or Docker failed to set a run up. The build log is in `data/logs/`.

## A request end to end

What happens on `POST /responses`, in order, and where in the code:

1. **Resolve** (`responses.py`). Look up the harness named by `model`, then its provider, then its
   sandbox. With `previous_response_id`, load that record and check it was made on the same
   harness.
2. **Record** (`models.py`). Create a `Response` with `status: in_progress`. Its workspace is the
   previous response's, or `data/workspaces/{id}` for a new conversation. Its session id is the
   previous response's.
3. **Workspace** (`workspace.py`). Create the directory with `.hi/` inside it. On first use, run
   `git init` and write a `.gitignore` for the internal paths.
4. **Prepare** (`runner.py`).
   - Write the request's input files and the harness's templated `files` into the workspace.
   - Write the request JSON to `.hi/request.json`.
   - Build the environment: the `HI_*` contract plus the harness's templated `run.env`.
   - Template `run.argv`.
5. **Baseline**. Commit the workspace with git, so only what the harness itself writes counts as produced.
6. **Image** (`sandbox.py`).
   - The tag is `harness-interface/{sandbox}:{first 12 hex of sha256(Dockerfile)}`.
   - If that image exists, use it. Otherwise `docker build` it from the Dockerfile with an empty context, one build per tag at a time.
   - The build log goes to `data/logs/build-{sandbox}-{hash}.log`.
7. **Network and door**.
   - Hand the workspace to uid 1000 if the server runs as root.
   - Create an internal network, `harness-net-{id}`.
   - Start the egress door, `harness-door-{id}`, on it: `python:3.12-alpine` running `egress.py` with the allowlist.
   - Connect the door to Docker's bridge network, so it alone can reach out.
   - Wait, for up to 10 seconds, until the door reports that it is listening.
8. **Run**. Start `harness-run-{id}` with `docker run --rm -i`:
   - on the internal network, with the hardening below;
   - the workspace mounted at `/workspace`, the scripts read-only at `/harness`;
   - `HTTPS_PROXY` pointing at the door;
   - the environment passed by name, so values never appear on a command line;
   - the request JSON on stdin and stderr to `data/logs/{id}.log`.

   The record is saved, and the timeout clock starts.
9. **Stream**. Copy stdout to `data/logs/{id}.out` as it arrives. With `stream`, each line also
   goes out as a `harness.output` event.
10. **Finish**.
    - Wait for the exit code, then remove the door and the network.
    - Read `.hi/output.json`.
    - Decide the status: timeout or cancel wins, then the reported `status`, then the exit code.
    - Fold the answer, usage, cost and session id into the record.
    - List the produced files with `git status`, then commit the workspace again.
    - Save the record and return it, or send it as `response.completed`.

With `HI_RUNTIME=local`, steps 6 to 8 are a plain subprocess in the workspace directory, with
the same environment and stdin, killed by process group on timeout or cancel.

## The sandbox

Every run gets the same hardening, whatever its sandbox:

- all capabilities dropped and `no-new-privileges`, so nothing can escalate;
- a read-only root filesystem;
- a 512 MB tmpfs at `/tmp` that allows exec, as a normal `/tmp` does, because CLIs unpack native
  modules there and load them;
- a limit of 512 processes and 4 GB of memory;
- a workspace owned by the sandbox user, uid 1000; a server running as root hands it over before
  each run;
- an internal Docker network of its own, with no route to the internet, the host or other runs.
  Its only other member is the egress door.

The door is `egress.py`, a CONNECT-only tunnel. Its allowlist is the host and port of the
harness's provider, plus whatever the sandbox's `egress` names.
- It resolves names itself, so the sandbox needs no DNS.
- TLS stays end to end, so the door sees nothing.
- Anything that is not a CONNECT to an allowed host and port gets a 403. That includes plain
  HTTP, other ports, and requests aimed at the door itself.
- The door runs with every capability dropped and a read-only root.

A harness can call its model and nothing else, and the door cannot be used for anything but that.

`HI_RUNTIME=local` skips all of this. It is for development and tests, and every record it
makes says `"runtime": "local"`.

## Data

Everything lives under `HI_DATA_DIR`:

```
providers/{name}.json        mode 600, in a mode 700 directory: the keys
sandboxes/{name}.json
harnesses/{name}.json
scripts/{harness}/           the harness's scripts, mounted read-only into its runs
responses/{id}.json          the records
logs/{id}.out, {id}.log      each run's stdout and stderr; build-*.log for image builds
workspaces/{id}/             one per conversation, named after its first response; a git repository
```

## Layout

```
harness_interface/
  app.py           the routes, and main(), the entry point
  config.py        Settings, from the environment
  models.py        Provider, Sandbox, Harness, the request, the Response record
  registry.py      the three resources; the built-in default sandbox; a harness's scripts on disk
  responses.py     one response end to end, and the wire format in and out
  runner.py        the process contract: files, env, request.json, output.json
  sandbox.py       Docker (image, network, door, run, kill) and the local subprocess runtime
  egress.py        the door
  workspace.py     a conversation's directory, its git baseline, produced files
  store.py         one JsonStore class for the four stores
  template.py      {name} placeholders
  default.Dockerfile
harnesses/         twenty-five harnesses, one folder each; harnesses/README.md registers them
docs/              this, the walkthrough, media
tests/             every endpoint through an echo harness on the local runtime; the door; the docker command lines
```

## Verified

The live test ran on Docker with runc:
1. The server was started with `uv run harness-interface`.
2. Four providers were added through the API: Anthropic, OpenAI, and DeepSeek's Anthropic and
   OpenAI endpoints. All 25 shipped harnesses were added the same way, with no restart.
3. The default image was built once, on the first request. Every run after that was a new
   container from it.

Each harness got two turns. The first asked it to remember a word and answer `17 * 23`. The
second, sent with `previous_response_id`, asked it to recall the word. 23 harnesses answered 391,
and all 23 recalled the word:
aider, cheetahclaws, claude-code, cline, codex, deepseek-harness, gajae, goose, grok-cli,
harness-engineering, hermes, jcode, kilo, kimi-code, mimo, minimax-code, nanobot, omp, opencode,
openhands, opensquilla, pi, qwen-code. Gemini CLI and Qoder were not run, for want of a key.

A probe ran inside a live run, as the sandbox user. It found:
- no capabilities, and no way to escalate;
- no DNS, no direct connection out, and no connection to the Docker host;
- `/etc` and `/usr` read-only;
- through the door, only the provider's host on its own port, from the very first instant of the run, and nothing else.

The tests also cover the docker command lines, the image tagging, the wait for the door and the
door itself.

## Trust

Single tenant. The API binds to localhost and has no authentication, so keep it there. Provider
keys are stored as mode-600 files under `data/providers/`. They enter a run only as environment
variables inside its container. A harness is code you chose to run: the sandbox limits what it
can reach, not what it does to its own workspace.
