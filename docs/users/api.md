# HTTP API

The server's whole surface. It listens on `http://127.0.0.1:8000` by default; bodies are JSON.
FastAPI also serves the schema at `/openapi.json` and interactive docs at `/docs`.

| Method | Path | |
|---|---|---|
| PUT | `/providers/{name}` | add or replace a provider |
| GET | `/providers`, `/providers/{name}` | list, or get one; the key is never returned |
| DELETE | `/providers/{name}` | remove it |
| PUT | `/harnesses/{name}` | add or replace a harness folder, and start its install |
| GET | `/harnesses` | every harness, with its install state |
| GET | `/harnesses/{name}` | one harness, with its install state and log, and its files |
| DELETE | `/harnesses/{name}` | remove it |
| POST | `/responses` | start a session, or continue one: the OpenAI Responses API |
| GET | `/sessions` | every session, without its responses |
| GET | `/sessions/{id}` | a session and all its responses; `?stream=true` follows it |
| POST | `/sessions/{id}/interrupt` | put more text into a session |
| POST | `/sessions/{id}/stop` | stop what it is running |

Refusals: **400** the request can't be done (an unknown harness or provider, a shape the harness doesn't
speak, a continued session on another harness, a harness whose install failed), **404** it names
something that doesn't exist, **409** the session already has a response running (interrupt it instead),
**422** the body is malformed. The body is `{"detail": "…"}`. A harness that fails is not an HTTP error:
its response says why.

## Providers

```json
PUT /providers/anthropic
{"url": "https://api.anthropic.com", "api": "anthropic-messages", "key": "sk-ant-…"}
```

`api` is `anthropic-messages`, `openai-responses` or `openai-chat`. `url` is the base URL the shape's
official SDK takes: `anthropic-messages` without a version path, `openai-*` with one
(`https://api.openai.com/v1`). The reply, and every `GET`, shows `name`, `url` and `api`, never the key.

## Harnesses

A harness is a [folder](harnesses.md), sent as a map of relative path to content: its text, or
`{"base64": "…"}` for a file that isn't UTF-8.

```json
PUT /harnesses/claude-code
{"harness.json": "{…}", "install.sh": "…", "run.sh": "…", "adapter.py": "…", "hi_adapter.py": "…",
 "home/.claude/settings.json": "{…}"}
```

It is stored only if it is a valid contract-1 folder named as in the path. Storing it starts its install
in the background; replacing it installs again. `GET` shows
`"install": {"state": "installing" | "ready" | "failed", "log": "…", "error": "…"}`. A request for a
harness still installing waits for the install.

## POST /responses

The OpenAI Responses shape:

| Field | |
|---|---|
| `model` | `harness[@provider][/model]`: `claude-code`, `claude-code/claude-sonnet-4-6`, `claude-code@deepseek/deepseek-chat`. With no provider, the one registered for the harness's default URL and shape. |
| `input` | the task: a string, or a list of `{"type": "input_text", "text"}`, `{"type": "input_file", "filename", "file_data"}` and `{"type": "message", "role": "user", "content"}` items. `file_data` is the file's text, or a `data:<type>;base64,…` URL. Files are written into the workspace. |
| `instructions` | rendered into the harness's `files`, where its CLI reads instructions |
| `previous_response_id` | continue that response's session, on the same harness and provider |
| `stream` | `true` for server-sent events |
| `metadata` | any object, kept on the response |

Without `previous_response_id` it starts a new session: a fresh workspace. With it, the same session
continues: the same workspace and `.home`, and the CLI resumes its own conversation. A session runs one
response at a time.

Without `stream` the reply is the finished response. With it, server-sent events (below). Either way
the `X-Response-Id` and `X-Session-Id` headers carry the ids at once, and the response belongs to the
server: leaving early stops the following, never the work.

## The response

```json
{
  "id": "resp_…", "object": "response", "created_at": 1792540000.1, "status": "completed",
  "model": "claude-code", "instructions": "Answer in one line.", "input": "What is 17 * 23?",
  "previous_response_id": null,
  "output": [{"type": "message", "id": "msg_…", "role": "assistant", "status": "completed",
              "content": [{"type": "output_text", "text": "391", "annotations": []}]}],
  "usage": {"input_tokens": 10587, "output_tokens": 6, "total_tokens": 10593,
            "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
  "error": null, "incomplete_details": null, "metadata": {},
  "harness": {
    "session": "sess_…", "name": "claude-code", "provider": "anthropic", "exit_code": 0, "latency_s": 9.4,
    "usage": {"input_tokens": 10587, "output_tokens": 6, "cache_read_tokens": 0, "cache_write_tokens": 0,
              "reasoning_tokens": 0},
    "cost_usd": 0.032, "resume": "1edd94d2-…",
    "stdout": "…everything it printed on stdout…", "stderr": "…",
    "diff": "…a unified diff of this response's changes…",
    "changes": {"notes.txt": "plan: build a calculator\n", "old.txt": null},
    "files": ["notes.txt"],
    "home": {".claude/projects/…/memory/MEMORY.md": "…"},
    "output": {"answer": "391", "status": "ok", "resume": "1edd94d2-…", "usage": {…}, "cost_usd": 0.032, "steers": 0},
    "steers": [], "undelivered": [], "stop": null, "base": "…", "commit": "…"
  }
}
```

| Field | |
|---|---|
| `status` | `in_progress`, then `completed`, `failed`, `incomplete` (its time limit stopped it) or `cancelled` (stopped, or interrupted) |
| `output` | the harness's answer as one assistant message; empty if it gave none |
| `error` | when `failed`: `{"code", "message"}`; `code` is `harness_failed`, `failed_to_start`, `server_restarted` or `internal_error` |
| `harness.stdout`, `harness.stderr` | everything it printed, so far while it runs |
| `harness.diff`, `harness.changes` | the workspace's changes: a diff, and each changed file's new content (`null` if deleted); a file that isn't UTF-8 is `{"base64": "…"}` |
| `harness.files` | every file in the workspace after the response |
| `harness.home` | the reported artifacts (the folder's `report`) that the response added, changed or deleted |
| `harness.output` | everything the harness wrote to its result file, its own keys too |
| `harness.resume` | the CLI's handle to its conversation |
| `harness.steers`, `harness.undelivered` | the text sent into the response, and any it didn't take |
| `harness.stop` | `stopped` or `killed` when it was asked to stop |
| `harness.base`, `harness.commit` | the workspace's snapshots before and after |

`.home/` (the CLI's own state), `.git/` and the server's files are never listed, diffed or returned as
the session's work; only `report` brings files back from `$HOME`.

## Streaming

| Event | Data |
|---|---|
| `response.created` | `{"response": <the response, in_progress>}` |
| `harness.stdout` | `{"response": "resp_…", "line": "…"}`, one per line the harness prints on stdout |
| `harness.stderr` | the same, for stderr |
| `harness.steer` | `{"response", "input", "at"}`: text sent into the running response, in order with its output |
| `session.interrupted` | `{"response", "from", "outcome", "input", "at"}`: the session continues with new text, in a new response |
| `response.completed` | `{"response": <the finished response>}` |

Every event also carries `type` (its name) and `sequence_number`.

## Sessions

```json
{"id": "sess_…", "object": "session", "status": "active", "harness": "claude-code", "provider": "anthropic",
 "model": "", "interrupt": "steered", "resume": "…", "created_at": …, "updated_at": …,
 "interrupts": [{"at": …, "input": "…", "outcome": "steered", "response": "resp_…"}],
 "responses": [ …every response, oldest first… ]}
```

`status` is `active` while a response runs, else `idle`. `interrupt` is the harness's tier, so a client
knows what an interrupt will do. `GET /sessions` lists sessions without their responses.
`GET /sessions/{id}?stream=true` follows the session's events from its current response on, through any
continuations, until it is idle; on an idle session the stream ends at once.

### POST /sessions/{id}/interrupt

```json
{"input": "Stop counting; write DONE to done.txt instead.", "instructions": null, "stream": false}
```

It degrades by the harness's tier and replies `{"outcome", "response"}`:
- **`steered`:** a `steered` harness is running, and the text went into the running work. The reply is
  that response, at once.
- **`continued`:** the session was idle, or its harness can't be steered: the running response (if any)
  was stopped, and the session continues with the text in a new response. The reply waits for it.
- **`responded`:** as `continued`, for a harness that promises no resume.

With `"stream": true` it replies with the events instead. Text a response didn't take before ending is
sent again, joined, as the next response when it ended `completed`.

### POST /sessions/{id}/stop

```json
{"timeout_s": 20}
```

SIGINT to the harness, and a kill if it hasn't ended `timeout_s` later (the harness's `stop_timeout_s`
by default). It replies once nothing is running: `{"outcome": "stopped" | "killed" | "idle", "session"}`.
A stopped session can be continued later with `previous_response_id`.
