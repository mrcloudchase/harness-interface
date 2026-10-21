# API reference

Every route takes `Authorization: Bearer <key>`. A member's key names its org. Refusals are
`{"detail": "…"}` with 400 (cannot be done as asked), 401 (no or bad key), 403 (not your role),
404 (unknown, or not yours), 409 (busy), 422 (malformed body).

| Route | Who | What |
|---|---|---|
| `POST /v1/orgs` `{name, owner, max_runs}` | admin key | Create an org, its owner and the owner's first key. |
| `GET /v1/orgs` | admin key | List orgs. |
| `GET /v1/me` | any member | Your org, name and role. |
| `POST /v1/members` `{name, role}` | owner | Add a member (`owner` or `member`). |
| `GET /v1/members` | owner | List members. |
| `POST /v1/members/{name}/keys` `{label}` | owner, or the member | Mint a key; the secret is in the answer once. |
| `GET /v1/keys` | any | Your keys (every key, for an owner). |
| `DELETE /v1/keys/{id}` | owner, or its member | Revoke. |
| `PUT /v1/providers/{name}` `{url, api, key}` | owner | Register or replace. |
| `GET /v1/providers`, `GET /v1/providers/{name}` | any | Without keys. |
| `DELETE /v1/providers/{name}` | owner | |
| `PUT /v1/sandboxes/{name}` `{image \| dockerfile, egress, memory, pids}` | owner | Register or replace. |
| `GET /v1/sandboxes`, `GET /v1/sandboxes/{name}` | any | |
| `DELETE /v1/sandboxes/{name}` | owner | |
| `PUT /v1/harnesses/{name}` (body: a tar archive) | owner | Validate and store a version; make it current. |
| `GET /v1/harnesses`, `GET /v1/harnesses/{name}` | any | The current version and its `harness.json`. |
| `DELETE /v1/harnesses/{name}` | owner | Every version. |
| `POST /v1/responses` | any | A turn ([requests](requests.md)). |
| `GET /v1/responses/{id}` `?stream=true` | any | The response; streamed or replayed as events. |
| `POST /v1/responses/{id}/cancel` | any | Stop it. |
| `GET /v1/sessions` | any | Yours; everyone's for an owner. |
| `GET /v1/sessions/{id}` | any | |
| `POST /v1/sessions/{id}/interrupt` `{input}` | any | Steer the running turn. |
| `GET /v1/sessions/{id}/trace` | any | Requests, responses, interrupts, cancels, in order. |
| `GET /v1/sessions/{id}/archive` | any | The workspace, `application/gzip`. |
| `DELETE /v1/sessions/{id}` | any | |

`GET /docs` is the interactive OpenAPI page.
