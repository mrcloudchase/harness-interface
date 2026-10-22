# Architecture

One package, numbered layers, each importing only its layer or below (`tests/test_layers.py` enforces it).

| Layer | Modules | Responsibility |
|---|---|---|
| 0 | `errors`, `execution`, `secrets`, `files` | refusals; what running something means; the vault; symlink-safe reads and writes under a sandbox's trees |
| 1 | `runtimes.process`, `runtimes.docker`, `runtimes.door`, `runtimes/turn.sh` | one process as an Execution; a hardened container per run; the door (address rule, forwarder); the in-container runner that runs `request.sh` then `response.sh` |
| 2 | `harness` | the package contract: unpack, validate, digest, pack, seeds |
| 3 | `records`, `blobs`, `limits`, `store`, `catalog` | one table (SQLite or Postgres); one bucket (a directory or S3); the ceilings; tenants, members, keys, providers, packages, workers, tokens; the shipped packages |
| 4 | `sandboxes`, `gateway` | a node's base image, tools layers and runtimes; the gateway service |
| 5 | `sessions`, `worker` | the control plane's turn queue, sessions, reach, follow, cancel, steer; the worker that pulls and runs turns |
| 6 | `api.config`, `api.wire`, `api.auth`, `api.app`, `api.deployer`, `api.internal`, `__main__` | settings; the Responses format; principals; the routes; the roles |

## A turn's path

1. `POST /v1/responses` → `wire.ResponseRequest.ask` → `Sessions.create`: validates the tenant,
   harness, provider and continuation; writes the session and the response record (status `queued`)
   and the request to the trace; files go to a blob.
2. A worker's `claim` → `Sessions.claim`: the oldest queued turn whose tenant has a free slot, taken
   by compare-and-set; the job carries the package config, the tenant's ceilings, presigned URLs for
   the package archive, the snapshots and the files, and a session token minted for this turn.
3. `Worker._run`: unpack the package once, build its tools layer once (`install.sh` in the base
   image, unprivileged, with the install egress), restore the snapshots when stale, copy seeds and
   files through `files.write`, write the prompt and `request.json`, start the container with
   `turn.sh`, stream stdout and stderr as chunk records, obey cancels and steers from heartbeats,
   read `response`, `stdout`, `stderr` through `files.read`, snapshot the workspace and home, report.
4. The sandbox's provider calls go `hi-provider:8080` → the door's forwarder → the gateway, which
   resolves the token, opens the sealed key, allows the API shape's paths, forwards over TLS, counts
   and captures.
5. `Sessions.result`: the status from the outcome and exit code, the output capped, the trace's
   response entry, the session's snapshot pointer, usage seconds.

## Roles

`api` and `gateway` are stateless over records and blobs and hold the master key. `worker` holds a
credential and caches. `all` runs the three in one process. Followers of a running turn poll chunk
records, so any `api` replica serves any stream.

## The invariants

[docs/users/security.md](../users/security.md) lists them with their tests. When you touch
`docker.py`, `door.py`, `files.py`, `gateway.py` or `sessions.py`, read that table first.
