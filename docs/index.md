# Harness Gateway

<figure class="shot" markdown>
![Picky, the mascot: a hermit crab with no shell of its own](assets/picky.svg){ width="200" }
</figure>

A multi-tenant platform that runs coding-agent CLIs, the **harnesses**, one turn at a time in
sandboxes it owns, and exposes them through the **OpenAI Responses API**. A tenant brings two
things: its **providers** (model endpoints and their keys, sealed on arrival) and its **harness
packages** (how to install a CLI, how to run one turn, what to return). The platform decides
nothing about the output. It carries bytes in and bytes out and says whether the turn ended well.

```
                 OpenAI Responses API (any SDK, curl, the app)
                                  │
    api  ─── records (SQLite | Postgres) ─── blobs (directory | S3)
    gateway  holds the provider keys, relays provider calls, meters, captures
    worker   joins with a token, pulls turns, runs each in a fresh sandbox
                                  │
         sandbox: the package's CLI, a door as its only way out, a token instead of a key
```

The same image is the hosted platform and the self-hosted one. One box runs every role in one
process; a fleet runs them apart. Nothing in the package names a cloud.

## Where to go

| You want to | Read |
|---|---|
| Stand the platform up | [Deploy](deploy.md), then [Initialize](initialize.md) |
| Use a tenant: keys, providers, packages, a first request | [The app](app.md) through [First request](first-request.md) |
| Drive sessions: continue, steer, cancel, read the record | [Sessions](sessions.md), [Steer and cancel](steer-and-cancel.md), [Traces and captures](traces-and-captures.md) |
| Call it from code | [Clients](clients.md) |
| Run it for others: tenants, limits, workers | [Tenants and limits](tenants.md), [Workers and scale](workers.md) |
| Write or adapt a package | [Write a package](packages.md), [The catalog](catalog/index.md), [Demos](demos.md) |
| Know what it promises | [Security](security.md) |

## What a turn is

A member sends `POST /v1/responses` with `model` naming a harness and `input` holding the task.
The control plane queues the turn. A worker claims it, fetches the package and the session's last
snapshot, and starts a fresh container: no capabilities, a read-only root, the tenant's uid and
ceilings, and a door as its only route out. Inside, the package's `request.sh` runs the CLI with
the prompt. The CLI's provider calls go through the door to the gateway, which swaps the turn's
token for the real key, relays the call, meters it and keeps a capture. Output streams back as it
is written. When `request.sh` ends, `response.sh` decides what the response carries. The worker
snapshots the workspace and reports; the caller gets one assistant message with that text.

[Architecture](architecture.md) walks the same path through the code.

## Watch it

Six harnesses taking a streamed turn and a steer, recorded as they ran: [Demos](demos.md).
