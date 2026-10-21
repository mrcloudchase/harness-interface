# Requests

`POST /v1/responses` is the OpenAI Responses API. Any client that speaks it works unchanged; the
examples use curl and the official Python SDK.

```json
{
  "model": "claude-code-devteam",
  "input": "Fix the flaky test in test_client.py and run the suite.",
  "instructions": "Keep the diff small.",
  "metadata": {"sandbox": "py312-gpu", "provider": "deepseek", "model": "deepseek-chat"},
  "previous_response_id": null,
  "store": true,
  "stream": false,
  "background": false
}
```

| Field | Meaning |
|---|---|
| `model` | The harness's name. |
| `input` | Text, or Responses items: `input_text` parts and `input_file` parts (`filename` and `file_data`, text or a `data:…;base64,` URL) that land in the workspace before the turn. |
| `instructions` | Reaches the script as `HI_INSTRUCTIONS`; what it does with them is the harness's. |
| `metadata` | `sandbox`, `provider` and `model` override `harness.json`'s defaults for this request. Other keys are kept and echoed back. |
| `previous_response_id` | Continue that response's session: same workspace, same `$HOME`, `HI_TURN` one higher. |
| `store` | `true` keeps the session's workspace for continuation and archive. `false` keeps only the response and the trace. |
| `stream` | Server-sent events as the harness prints. |
| `background` | Return at once with `status: in_progress`; poll `GET /v1/responses/{id}`. |

Other Responses fields (`temperature`, `tools`, …) are accepted and ignored: the harness decides
those things.

## What comes back

```json
{
  "id": "resp_…", "object": "response", "status": "completed", "model": "claude-code-devteam",
  "previous_response_id": null, "store": true, "error": null, "incomplete_details": null,
  "output": [
    {"type": "message", "id": "msg_…0", "role": "assistant", "status": "completed",
     "content": [{"type": "output_text", "text": "…everything request.sh wrote to stdout…", "annotations": []}]},
    {"type": "message", "id": "msg_…1", "role": "assistant", "status": "completed",
     "content": [{"type": "output_text", "text": "…everything it wrote to stderr…", "annotations": []}]}
  ],
  "metadata": {"session_id": "sess_…", "harness": "claude-code-devteam", "version": "929aa748cf90e7cb",
               "sandbox": "py312-gpu", "provider": "deepseek", "model": "deepseek-chat", "turn": "1", "exit_code": "0"},
  "usage": null
}
```

- `output[0]` is stdout, `output[1]` is stderr, verbatim. A stock client's `output_text` is the
  two joined. Nothing is filtered: if the CLI printed JSON lines, that is what you get, and your
  program parses them.
- `status`: `completed` (exit 0), `failed` (`error.code` is `exit_status` with the code in the
  message, or `server_error` when the run could not be set up), `cancelled`, `incomplete` (the
  wall-clock cap), `in_progress`.
- `metadata` echoes yours and adds what ran: the session, the harness version, the sandbox, the
  provider, the model, the turn and the exit code.
- `usage` is empty. Token counts are in the output when the CLI prints them.

## Streaming

With `stream: true` the standard events arrive: `response.created`, two `response.output_item.added`
(stdout then stderr), a `response.output_text.delta` for every chunk as it is written, with
`output_index` 0 or 1, then the `done` events and `response.completed` (or `response.failed`;
`response.incomplete` carries a cancelled or timed-out response). `GET /v1/responses/{id}?stream=true`
follows a background response the same way, or replays a finished one.

```python
for event in client.responses.create(model="claude-code", input="…", stream=True):
    if event.type == "response.output_text.delta":
        print(event.delta, end="")
```

## Sessions

A response with no `previous_response_id` starts a session: a directory with the workspace, a run
directory, the responses and a trace. `previous_response_id` continues it; one turn at a time
(409 while one runs). A session is one harness version for its life.

| Route | What |
|---|---|
| `GET /v1/sessions` | Your sessions (every member's, for an owner). |
| `GET /v1/sessions/{id}` | Its harness, version, member, `stored`, `status` (`running` or `idle`) and response ids. |
| `POST /v1/sessions/{id}/interrupt` `{"input": "…"}` | Steer the running turn: the text to `$HI_DIR/interrupt`, then the harness's signal. 409 when nothing runs. |
| `POST /v1/responses/{id}/cancel` | SIGTERM, then SIGKILL after the harness's grace. The response ends `cancelled` with the output so far. |
| `GET /v1/sessions/{id}/trace` | Every request body and response object, every interrupt and cancel, with times, in order. |
| `GET /v1/sessions/{id}/archive` | The workspace as a gzipped tar: the artifacts. |
| `DELETE /v1/sessions/{id}` | Everything the session holds. |

## Files in, artifacts out

Files go in as `input_file` parts and land in the workspace under their `filename` before the turn.
A whole repository goes the same way as a tarball the script unpacks, or `request.sh` clones it
itself if the sandbox's egress allows the host; a token for that lives in the org's seeds or a
request file, never in a provider.

Artifacts come out as the workspace archive of a stored session, which holds whatever the harness
left there. A stateless request (`store: false`) keeps no workspace: have the script print what
matters, or ship it where it belongs before exiting.

## Stateless and stateful

`store: true` is a conversation: the workspace and the CLI's own memory persist, every turn sees
the last, the archive is there when you want it, and the session is yours to delete.
`store: false` is a function call: the turn runs in a fresh workspace, the response comes back,
and nothing but the response and its trace remains. The member's `$HOME` is updated either way,
because that is the CLI's own memory of the member; a harness whose `seeds/user` is empty and
whose CLI keeps nothing has none.
