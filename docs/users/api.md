# API reference

Every route takes `Authorization: Bearer <key>`: a member's `hi_…` key, the deployer's `hd_…` key, or a
worker's credential, as the row says. Refusals are `{"detail": …}` with 400 (cannot be done), 401, 403,
404 (unknown), 409 (busy) or 422 (malformed).

| Route | Who | What |
|---|---|---|
| `GET /healthz` | anyone | status, version, roles, whether sign-up is open |
| `POST /v1/signup` | anyone, when `HI_SIGNUP=open` | `{tenant, owner}` → the owner's key, once |
| `GET /v1/me` | member | who you are, your tenant's ceilings and status |
| `POST /v1/members`, `GET /v1/members` | owner | add a member (`{name, role}`), list them |
| `POST /v1/members/{name}/keys` | member (self) or owner | mint a key (`{label}`) → the secret, once |
| `GET /v1/keys`, `DELETE /v1/keys/{id}` | member (own) or owner | list, revoke |
| `PUT /v1/providers/{name}` | owner | `{url, api, key}`; the key is sealed |
| `GET /v1/providers`, `GET /v1/providers/{name}`, `DELETE …` | member / owner | without keys |
| `GET /v1/catalog`, `GET /v1/catalog/{name}` | member | the shipped packages and their verification |
| `PUT /v1/harnesses/{name}` | owner | a tar body: upload; a JSON body `{"catalog": …}`: fork |
| `GET /v1/harnesses`, `GET /v1/harnesses/{name}`, `DELETE …` | member / owner | versions and config; never the files |
| `POST /v1/responses` | member | the OpenAI Responses request ([requests](requests.md)) |
| `GET /v1/responses/{id}` | member | the response; `?stream=true` as events; `?detail=true` with raw streams |
| `POST /v1/responses/{id}/cancel` | member | stop it |
| `GET /v1/responses/{id}/captures`, `…/captures/{name}` | member | the door log and the provider exchanges |
| `GET /v1/sessions`, `GET /v1/sessions/{id}` | member | sessions, one session |
| `POST /v1/sessions/{id}/interrupt` | member | `{input}`: steer the running turn |
| `GET /v1/sessions/{id}/trace`, `GET /v1/sessions/{id}/archive`, `DELETE /v1/sessions/{id}` | member | the record, the workspace, removal |
| `POST /v1/tenants`, `GET /v1/tenants`, `GET /v1/tenants/{name}`, `PATCH …`, `DELETE …` | deployer | tenants, their ceilings and status, their usage |
| `GET /v1/workers`, `DELETE /v1/workers/{id}` | deployer | the fleet's workers |
| `GET /v1/fleet` | deployer | counts across the platform |
| `POST /internal/join` | the join token | a worker's credential |
| `POST /internal/heartbeat`, `/claim`, `/turns/{id}/started`, `/turns/{id}/chunks`, `/turns/{id}/result` | worker | the worker protocol |
| `GET`/`PUT /internal/blobs/{token}` | the signed token | blob access for the directory backend |

Interactive documentation is at `/docs`.
