# Requests

`POST /v1/responses` is the OpenAI Responses API. Every field goes somewhere the package can read;
the response carries what the package returned and nothing the platform made up.

## The request

| Field | Where it goes |
|---|---|
| `model` | `harness` (the package's defaults) or `harness/provider/model` (the model last, so it may hold slashes). Anything else is 422. |
| `input` | A string, or items. `input_text` items join into the prompt on `request.sh`'s stdin. `input_file` items (`filename`, `file_data` as text or a `data:…;base64,` URL) land in the workspace before the turn; they win over a seed with the same name. |
| `instructions` | `HI_INSTRUCTIONS`. The package decides what it means. |
| `previous_response_id` | Continue that response's session: the same workspace and home, `HI_TURN` one higher. A continuation must name the session's harness; the provider and model may change per turn. |
| `store` | `false` keeps the response and the trace and no workspace, so it cannot be continued. |
| `stream` | Server-sent events: `request.sh`'s stdout as `response.output_text.delta`s, then the final response. |
| `background` | Return at once with `in_progress`; poll `GET /v1/responses/{id}`, or stream it later with `?stream=true`. |
| `metadata` | Echoed on the response; in `HI_REQUEST` for the package. |
| anything else | Ignored, and in `HI_REQUEST` for the package. |

The whole body, as sent, is also written to `$HI_REQUEST` for the package and kept in the trace,
with files recorded as names and sizes.

## The response

The standard object. `model` is the path that ran; `output` is one assistant message whose text is
what `response.sh` printed (or `request.sh`'s stdout without one); `status` is `completed` when the
package exited 0, `failed` with `error` otherwise, `cancelled` after a cancel, `incomplete` after the
timeout. `metadata` carries `session_id`, `harness`, `version`, `turn`, `exit_code` and the request's
own metadata. `?detail=true` adds `stdout` and `stderr`, the raw streams, including what has streamed so far while the turn runs. `X-Session-Id` is a header too.

## Sessions

A session is the chain of turns that continue each other. The workspace is snapshotted after every
turn and restored for the next, on whichever worker runs it; the member's home for that package
persists across sessions.

| Route | What |
|---|---|
| `GET /v1/sessions` | yours (owners: the tenant's), with status `running` or `idle` |
| `GET /v1/sessions/{id}` | the session: harness, version, member, turns |
| `POST /v1/sessions/{id}/interrupt` `{"input": "…"}` | steer the running turn: the text lands in `$HI_DIR/interrupt` and the package's signal reaches `request.sh` on the worker's next heartbeat (within five seconds); a turn that ends first is not steered. 409 when nothing runs |
| `POST /v1/responses/{id}/cancel` | stop it: SIGTERM, then SIGKILL after the package's grace; `response.sh` still runs; a queued turn ends at once |
| `GET /v1/sessions/{id}/trace` | every request, response, steer and cancel, as sent, in order |
| `GET /v1/sessions/{id}/archive` | the workspace after the last turn, as a gzipped tar |
| `GET /v1/responses/{id}/captures` | the turn's door log and every provider exchange the gateway relayed (`provider/0001.json`…), fetchable by name |
| `DELETE /v1/sessions/{id}` | removes it and everything it kept; 409 while it runs |

One turn at a time per session; `max_runs` at a time per tenant, the rest queued in order.

## Building on it

A single request is a call. An agent is a loop that reads the response and sends the next one with
`previous_response_id`. A benchmark runs the same task across harnesses and providers by changing
the model path and judges the archives. A harness built on a harness is a package whose `request.sh`
calls this API with a member's key. Nothing of that is in the platform, which is the point.
