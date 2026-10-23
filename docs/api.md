# API

Every route takes `Authorization: Bearer <key>`: a member's `hg_…` key, the deployer's `hgd_…`
key, or a worker's credential, as the row says. Refusals are `{"detail": …}` with 400 (cannot be
done), 401, 403, 404 (unknown), 409 (busy) or 422 (malformed). The interactive reference, with
every body's schema, is at `/reference` on your platform.

## Members

| Route | Who | What |
|---|---|---|
| `GET /healthz` | anyone | status, version, roles, whether sign-up is open |
| `POST /v1/signup` | anyone, when `HG_SIGNUP=open` | `{tenant, owner}` → the owner's key, once |
| `GET /v1/me` | member | who you are, your tenant's ceilings and status |
| `POST /v1/members`, `GET /v1/members` | owner | add a member (`{name, role}`), list them |
| `POST /v1/members/{name}/keys` | member (self) or owner | mint a key (`{label}`) → the secret, once |
| `GET /v1/keys`, `DELETE /v1/keys/{id}` | member (own) or owner | list, revoke |
| `PUT /v1/providers/{name}` | owner | `{url, api, key}`; the key is sealed |
| `GET /v1/providers`, `GET /v1/providers/{name}`, `DELETE …` | member / owner | without keys |
| `GET /v1/catalog`, `GET /v1/catalog/{name}` | member | the shipped packages and their verification |
| `PUT /v1/harnesses/{name}` | owner | a tar body: upload; a JSON body `{"catalog": …}`: fork |
| `GET /v1/harnesses`, `GET /v1/harnesses/{name}`, `DELETE …` | member / owner | versions and config; never the files |
| `POST /v1/responses` | member | the OpenAI Responses request |
| `GET /v1/responses/{id}` | member | the response; `?stream=true` as events; `?detail=true` with raw streams |
| `POST /v1/responses/{id}/cancel` | member | stop it |
| `GET /v1/responses/{id}/captures`, `…/captures/{name}` | member | the door log and the provider exchanges |
| `GET /v1/sessions`, `GET /v1/sessions/{id}` | member | sessions, one session |
| `POST /v1/sessions/{id}/interrupt` | member | `{input}`: steer the running turn |
| `GET /v1/sessions/{id}/trace`, `GET /v1/sessions/{id}/archive`, `DELETE /v1/sessions/{id}` | member | the record, the workspace, removal |

## The request

`POST /v1/responses` takes the OpenAI Responses request body:

| Field | Meaning |
|---|---|
| `model` | `harness` or `harness/provider/model` |
| `input` | a string, or a list of messages and parts: `input_text`, `input_file` (`filename`, `file_data` as a data URL or text) |
| `instructions` | reaches the package as `HG_INSTRUCTIONS` |
| `previous_response_id` | continue that response's session |
| `stream` | server-sent events |
| `background` | return at once with `in_progress` |
| `store` | `false` keeps no workspace |
| `metadata` | strings, returned on the response |

Fields the platform does not use are ignored and kept in the trace, and reach the package in
`HG_REQUEST`.

## The response

The standard response object. `output` holds one assistant message whose text is what the
package returned. `status` is `completed`, `failed` (with `error`), `incomplete` (timeout) or
`cancelled`. `metadata` carries `session_id`, `harness`, `version`, `turn`, `exit_code` and
`truncated` when the output was cut at the tenant's ceiling. `model` is the path that ran.
`usage` is null.

## Events

With `stream: true`: `response.created`, `response.in_progress`, `response.output_item.added`,
`response.content_part.added`, `response.output_text.delta` per stdout chunk,
`response.output_text.done`, `response.content_part.done`, `response.output_item.done`, then
`response.completed`, `response.failed` or `response.incomplete` with the whole response. The
`X-Session-Id` header names the session from the first byte.

## Deployer

| Route | What |
|---|---|
| `POST /v1/tenants` | `{name, owner, limits?}` → the tenant and the owner's key, once |
| `GET /v1/tenants`, `GET /v1/tenants/{name}` | tenants with usage; one tenant with members, provider and harness names |
| `PATCH /v1/tenants/{name}` | `{limits?, status?}` |
| `DELETE /v1/tenants/{name}` | the tenant and everything it owns |
| `GET /v1/workers`, `DELETE /v1/workers/{id}` | the fleet's workers; forget one |
| `GET /v1/fleet` | counts across the platform |
| `GET /v1/usage?days=N` | usage all time (`0`) or over the last N days: totals, per day, per tenant, per harness, by outcome |

## Workers

| Route | Who | What |
|---|---|---|
| `POST /internal/join` | the join token | `{name, slots, version}` → a worker credential |
| `POST /internal/heartbeat` | worker | `{running: [ids]}` → commands: cancels and steers per turn |
| `POST /internal/claim` | worker | a job, or 204 |
| `POST /internal/turns/{id}/started`, `…/chunks`, `…/result` | worker | the turn's progress and end |
| `GET`, `PUT /internal/blobs/{token}` | the signed token | blob access for the directory backend |
