# HTTP API

The server's whole surface. It listens on `http://127.0.0.1:8000` by default. Bodies are JSON.
FastAPI also serves the schema at `/openapi.json`, and interactive docs at `/docs`.

## Endpoints

| Method | Path | |
|---|---|---|
| PUT | `/providers/{name}` | add or replace a provider |
| GET | `/providers`, `/providers/{name}` | list, or get one; keys are never returned |
| DELETE | `/providers/{name}` | `{"deleted": true\|false}` |
| PUT | `/sandboxes/{name}` | add or replace a sandbox |
| GET | `/sandboxes`, `/sandboxes/{name}` | list (`default` first), or get one |
| DELETE | `/sandboxes/{name}` | `{"deleted": true\|false}` |
| PUT | `/harnesses/{name}` | add or replace a harness |
| GET | `/harnesses`, `/harnesses/{name}` | list, or get one |
| DELETE | `/harnesses/{name}` | `{"deleted": true\|false}` |
| POST | `/responses` | run a harness |
| GET | `/responses`, `/responses/{id}` | list every record, or get one |
| GET | `/responses/{id}/output` | the harness's stdout, byte for byte, in its declared content type |
| GET | `/responses/{id}/log` | its stderr |
| GET | `/responses/{id}/diff` | what the response changed, as a unified diff; live while it runs |
| GET | `/responses/{id}/files` | every file in the workspace, as the response left it |
| GET | `/responses/{id}/files/{path}` | one file, as the response left it |
| POST | `/responses/{id}/cancel` | `{"cancelled": true}` if the run was in flight |

## Resources

A PUT adds or replaces a resource, and the next request uses it. The `name` in the body must
match the one in the path. Names are lowercase letters, digits and dashes.

**Provider**

```json
{"name": "anthropic", "url": "https://api.anthropic.com", "key": "sk-ant-..."}
```

**Sandbox**

```json
{"name": "python-dev", "dockerfile": "FROM python:3.12-slim\n…", "egress": ["pypi.org"]}
```

`egress` lists hosts the run may reach besides its provider, as `host`, `host:port` or a URL.
`default` is built in, and can't be replaced or deleted.

**Harness:** `harness.json` plus its `scripts`. Every field is in the
[harness contract](harness-contract.md#harnessjson).

```json
{"name": "hello", "provider": "anthropic", "run": {"stdout": "text/plain"},
 "scripts": {"run.sh": "echo \"asked: $HI_TASK\"\n"}}
```

## POST /responses

The request is the OpenAI Responses shape:

| Field | |
|---|---|
| `model` | the harness's name, or `harness/model` to pass a model through to it |
| `input` | the task: a string, or a list of `{"type": "input_text", "text": …}` and `{"type": "input_file", "filename": …, "file_data": "<the file's text>"}` items. Files are written into the workspace. |
| `instructions` | text the harness can place for its CLI, as `{instructions}` |
| `previous_response_id` | continue that response's conversation |
| `stream` | `true` for server-sent events; otherwise one JSON object when the run ends |
| `metadata` | any object, kept on the record |

The server checks the request, prepares the workspace and starts the run. With `stream` it
answers at once; without it, when the run ends. Either way the run belongs to the server: it
finishes and is recorded whether or not the client stays.

### Without `stream`

The response is the finished record, when the run ends. The `X-Response-Id` header carries its id.

### With `stream`

Server-sent events. The `X-Response-Id` header carries the id from the start.

```
event: response.created
data: {"type": "response.created", "response": {…the record, in_progress…}}

event: harness.output
data: {"type": "harness.output", "line": "…one line the harness printed on stdout…"}

event: harness.log
data: {"type": "harness.log", "line": "…one line the harness printed on stderr…"}

event: response.completed
data: {"type": "response.completed", "response": {…the finished record…}}
```

There is one `harness.output` event for every line the harness prints on stdout, and one
`harness.log` event for every line on stderr, as they arrive. Together they are everything the
harness prints, as if you were watching it in a terminal. A client that disconnects only stops
following.

### Continuing

With `previous_response_id`, the run:
- uses the same harness, and that response's workspace, with the files as they were left;
- hands the harness the session id that response reported, so it resumes its own session.

A conversation runs one request at a time; a second one gets a 409 until the first ends.

## The record

```json
{
  "id": "resp_254e3da1d07b4a5f",
  "object": "response",
  "created_at": 1792309774.1,
  "status": "completed",
  "model": "claude-code",
  "instructions": "",
  "input": "Write a haiku about a hermit crab trying on shells.",
  "previous_response_id": null,
  "output": [{"type": "message", "role": "assistant", "status": "completed",
              "content": [{"type": "output_text", "text": "Tiny tenant seeks—…", "annotations": []}]}],
  "usage": {"input_tokens": 3, "output_tokens": 24},
  "error": null,
  "incomplete_details": null,
  "metadata": {},
  "harness": {
    "name": "claude-code", "provider": "anthropic", "sandbox": "default", "runtime": "docker",
    "image": "harness-interface/default:0e4419119ad6", "workspace": "…/workspaces/resp_254e3da1d07b4a5f",
    "session_id": "863ff72c-…", "exit_code": 0, "latency_s": 21.1, "cost_usd": 0.1174,
    "files": [], "deleted": [],
    "base": "3f1c9e2…", "commit": "a77d1b0…"
  }
}
```

| Field | |
|---|---|
| `status` | `in_progress`, then `completed`, `failed`, `incomplete` (timed out) or `cancelled` |
| `output` | the harness's reported answer, as one assistant message; empty if it reported none |
| `usage` | as the harness reported it, in its own keys |
| `error` | when `failed`: `{"code", "message"}`, where `code` is `harness_failed` (it ran and failed), `setup_failed` (it never ran), `server_restarted`, or `internal_error` (a bug) |
| `incomplete_details` | when it timed out: `{"reason": "timeout"}` |
| `harness` | what the Responses shape has no field for: where it ran, the session to resume, exit code, latency, cost; `files` it added or changed and `deleted`; and the workspace commits before (`base`) and after (`commit`) the turn |

## Errors

| Status | When |
|---|---|
| 400 | the path name and body name differ; a harness, provider, sandbox or previous response doesn't exist; a follow-up names another harness's response; a template is invalid; a name breaks the naming rule; an attempt to change or delete `default` |
| 404 | the provider, sandbox, harness or response isn't there, or the response has no output, log, diff or such file |
| 409 | the conversation already has a run in progress |
| 422 | the body doesn't fit its shape: `input` has no text, a field is missing, or a value is refused, such as a script name that isn't a plain filename, a non-positive timeout or an empty Dockerfile |

A 400, 404 or 409 body is `{"detail": "<what went wrong>"}`. A 422 body is FastAPI's list of
validation errors. A run that fails is not an HTTP error: its record says why.

## Seeing everything a harness did

Every turn ends in a commit in the conversation's workspace, so each response can be read as it
left things, even after later turns have changed them:

| | |
|---|---|
| `GET /responses/{id}/diff` | the turn's changes: added, modified and deleted files, as a unified diff. While the run is going, the changes so far. |
| `GET /responses/{id}/files` | every file in the workspace after the turn (now, while it runs) |
| `GET /responses/{id}/files/{path}` | one file after the turn; 404 if the turn deleted it |
| `GET /responses/{id}/output`, `/log` | everything it printed, byte for byte |

The harness's own state (`.home/`, where CLIs keep sessions and credentials) and the server's
(`.hi/`) are never committed, diffed, listed or served.
