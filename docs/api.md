# API reference

The HTTP API, precisely: the three resources, the contract between the server and a harness, the
request and response wire format, every endpoint and its errors. For how it works inside, see
[architecture.md](architecture.md); for a guided tour, [walkthrough.md](walkthrough.md).

The server listens on `http://127.0.0.1:8000` by default ([setup.md](setup.md#configure)). FastAPI
also serves the OpenAPI schema at `/openapi.json`, and interactive docs at `/docs`.

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
| `scripts` | `{}` | filename → content; stored under `scripts/{name}/` in the data directory and mounted read-only at `{harness_dir}`; names must be plain filenames |

Templates take `{task}`, `{instructions}`, `{model}`, `{session_id}`, `{workspace}`,
`{harness_dir}`, `{provider_url}` and `{provider_key}`.
- Only `{identifier}` is a placeholder, so JSON or code braces in a file pass through untouched.
- An unknown placeholder fails the request with a 400.
- `{workspace}` and `{harness_dir}` are the paths as the harness sees them: `/workspace` and `/harness` in Docker.

## The harness contract

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
That is the whole interface between the server and a harness. A minimal one is in
[walkthrough.md](walkthrough.md#8-write-your-own-harness).

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
- `status`: `in_progress` while it runs, then `completed`, `failed`, `incomplete` on timeout, or `cancelled`;
- `model`;
- `output`: one assistant message holding the harness's reported answer;
- `usage`, as the harness reported it;
- `previous_response_id` and `metadata`;
- `error` when it failed, with a `code`:
  - `harness_failed`: the harness ran and failed;
  - `setup_failed`: the sandbox could not be set up, so the harness never ran;
  - `server_restarted`: the server restarted while it ran;
- `incomplete_details` when it timed out;
- one extension key, `harness`, holding:
  - name, provider and sandbox;
  - runtime and image;
  - workspace and session id;
  - exit code, latency and cost;
  - produced files.

`POST /responses` checks the request, prepares the workspace and starts the run, then answers at
once. The run belongs to the server, not to the request that started it: it goes on, and is
recorded, whether or not the client is still there.

Streamed, the record arrives as SSE in the Responses framing:
1. `response.created`, sent at once, before the sandbox is set up;
2. one `harness.output` event, `{"line": ...}`, for each line of the CLI's stdout as it arrives;
3. `response.completed`, carrying the record.

A Responses client sees a valid start and end and can ignore the middle. A client that knows the
CLI reads its events exactly as printed. A client that disconnects only stops following; the
record, `/output` and `/log` have everything once the run is done. Without `stream`, the request
waits for the run and returns the finished record.

Runs go side by side: many clients, many harnesses, many conversations at once. A conversation
has one run at a time: a follow-up sent while its conversation still has a run in progress gets a
409.

`POST /responses/{id}/cancel` stops a run at any point. Cancelled while its sandbox is still being
set up, the harness never starts. Cancelled while running, the harness is killed. Either way the
record ends `cancelled`.

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
- 409 means the conversation already has a run in progress.
- 422 means the request body does not fit its shape, for example an `input` with no text.

A sandbox that fails to build, or a run Docker cannot set up, is not an HTTP error: the request
was fine. The record ends `failed`, with `setup_failed` and the reason. Image build logs are in
`logs/` in the data directory.
