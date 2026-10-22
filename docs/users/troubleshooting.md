# Troubleshooting

A response that did not complete says why in `error.message`; the trace and `?detail=true` hold
the rest. A refusal before a turn starts is an HTTP status with `{"detail": …}`.

| You see | It means | Do |
|---|---|---|
| `401 unknown or revoked API key` | the key is wrong, revoked, or its tenant is suspended | mint a new one; the deployer checks the tenant's status |
| `403 the deployer key manages tenants` | the deployer key on a tenant route, or the reverse | use the key the route takes |
| `404 no provider x` on a request | the package's defaults name a provider this tenant has not registered | register it under that name, or name yours in the model path |
| `400 no provider: name one…` | the package has no default provider | `harness/provider/model` |
| `422` on `model` | not a name or a three-part path | `harness` or `harness/provider/model` |
| `409 session … is running a response` | one turn at a time per session | wait, cancel it, or start a new session |
| `error: install.sh exited N; its log ends: …` | the CLI did not install | read the tail: a host missing from `install.egress` shows as a door refusal; fix and re-upload |
| `error: the package exited N` | `response.sh` (or `request.sh` without one) exited non-zero | `?detail=true` for stderr; a 401 from the provider means the CLI sent something other than the session token; a 403 from the gateway names a path it does not relay |
| `status: incomplete` | past the turn's timeout | raise `run.timeout_s` (within the tenant's ceiling) or shorten the task |
| `status: failed`, `the worker running it was lost` | the worker stopped heartbeating mid-turn | the session continues from its last snapshot; the deployer checks the worker |
| `metadata.truncated: true` | the output passed the tenant's `output_mb` | the record holds the first part; raise the ceiling or return less from `response.sh` |
| `the workspace is over the tenant's disk limit` | a snapshot passed `disk_mb` | clean the workspace or raise the ceiling |
| a steer returns 409 | nothing is running, or the turn is still queued | steer once it runs |
| the response is empty | `response.sh` printed nothing | that is the package's decision; `?detail=true` shows what `request.sh` printed |

The deployer sees workers at `GET /v1/workers` (`alive` is a heartbeat within 45 seconds) and the
queue at `GET /v1/fleet`. A turn's door log (`GET /v1/responses/{id}/captures/door.log`) lists every
host the sandbox tried to reach and whether the door allowed it.
