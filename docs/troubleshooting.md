# Troubleshooting

Every refusal is `{"detail": "…"}` with a status that says what kind: 400 cannot be done as
asked, 401 unknown key, 403 not allowed for this key, 404 no such thing, 409 busy, 422 malformed
body. A turn that ran and failed says why in `error`.

## Requests

| Symptom | Cause | Fix |
|---|---|---|
| `401 unknown or revoked API key` | the key is wrong, revoked, or its tenant is suspended | mint a new one; ask the deployer about the tenant |
| `403 the deployer key manages tenants; a member's key does this` | the deployer key on a member route | use a member's key |
| `404 no harness x` | no package by that name in this tenant | fork or upload it; `GET /v1/harnesses` lists them |
| `400 no provider: name one in the request's model path or in harness.json's defaults` | the package has no default provider and the request named none | register the provider the package expects, or use `harness/provider/model` |
| `404 no provider x` | the default or named provider is not registered | register it under that name |
| `409 session … is running a response` | one turn at a time per session | wait, cancel, or steer |
| `400 … was not stored, so it cannot be continued` | the previous turn ran with `store: false` | start a new session |
| `400 the request's files are over the tenant's upload limit` | files larger than `upload_mb` | smaller files, or ask the deployer |

## Turns

| `status` and `error` | Cause | Fix |
|---|---|---|
| `failed`, `install.sh exited N; its log ends: …` | the package's install failed on this worker | read the log tail; a refused host is missing from `install.egress`; a missing binary is missing from the base image |
| `failed`, `the package exited N` | `request.sh` or `response.sh` returned non-zero | `?detail=true` for stderr; a 401 from the provider usually means the CLI used a key of its own instead of the session token |
| `failed`, `the worker running it was lost` | the worker stopped heartbeating | the session continues from its snapshot; the deployer checks the Workers tab |
| `failed`, `could not start: …` | Docker could not start the sandbox | the worker's Docker daemon and disk; `docker info` on that machine |
| `incomplete`, `the turn ran past its timeout` | longer than `run.timeout_s` or the tenant's ceiling | raise the package's timeout within the ceiling, or split the task |
| `cancelled` | a cancel landed | expected |
| `completed` but `truncated: true` in metadata | output over `output_mb` | the package returns less, or the ceiling is raised |

## The sandbox cannot reach something

The door logs every decision. `GET /v1/responses/{id}/captures/door.log`:

```
door deny registry.npmjs.org:443
door allow api.github.com:443
gateway forward
```

A `deny` names a host the package did not list under `run.egress` (or `install.egress` for an
install). A refused private address is by design. A `gateway unreachable` line means
`HG_GATEWAY_URL` is wrong for this worker machine; on one box, where it is found, it means the
platform container was started without the Docker socket or outside the daemon it talks to.

## The platform

| Symptom | Fix |
|---|---|
| the first request to a package takes minutes | its install; the next one is fast |
| `GET /healthz` works, requests sit `queued` | no worker is alive, or every slot is busy; the dashboard shows both |
| the worker logs `could not reach the control plane` | `HG_CONTROL_URL` or the join token |
| a worker joined but its turns fail at once | the Docker socket it was given is not the daemon that runs it, so the paths it learned by inspecting itself are another machine's |
| sandboxes fail TLS on a network that re-signs it | `HG_CA_FILE` with the network's bundle |
| `set HG_MASTER_KEY (64 hex digits) or HG_MASTER_KEY_FILE` | run `serve` or `init`, or pass the key the fleet shares |
| the keys were not kept | they are in the container's log (`docker logs hg`) until it is removed; `init` makes new ones |
