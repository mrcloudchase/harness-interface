# Architecture

One Python package of about 3,500 lines in 27 files, in numbered layers. A module imports only
its own layer or below, and `tests/test_layers.py` fails when that changes.

| Layer | Modules | Responsibility |
|---|---|---|
| 0 | `errors`, `execution`, `secrets`, `files` | refusals; what running something means; the vault; symlink-safe reads and writes under a sandbox's trees |
| 1 | `runtimes.process`, `runtimes.docker`, `runtimes.door`, `runtimes/turn.sh` | one process as an Execution; a hardened container per run; the door (address rule, forwarder); the in-container runner that runs `request.sh` then `response.sh` |
| 2 | `harness` | the package contract: unpack, validate, digest, pack, seeds |
| 3 | `records`, `blobs`, `limits`, `store`, `catalog` | one table (SQLite or Postgres); one bucket (a directory or S3); the ceilings; tenants, members, keys, providers, packages, workers, tokens; the shipped packages |
| 4 | `sandboxes`, `gateway` | a node's base image, tools layers and runtimes; the gateway service |
| 5 | `sessions`, `worker` | the control plane's turn queue, sessions, reach, follow, cancel, steer; the worker that pulls and runs turns |
| 6 | `api.config`, `api.wire`, `api.auth`, `api.app`, `api.deployer`, `api.internal`, `__main__` | settings; the Responses format; principals; the routes; the roles |

## One request through the code

1. **The API authenticates.** The Bearer value is hashed and looked up; the key must be live and
   its tenant active. `wire.ResponseRequest.ask` turns the body into an `Ask`: harness, provider
   and model from `model`, text and files from `input`.
2. **The control plane queues.** `Sessions.create` opens a session or checks the continuation
   (stored, idle, same harness), chooses the provider, packs files into a blob, writes one record
   with status `queued`, marks the session running, and traces the request.
3. **A worker claims.** `Sessions.claim` scans queued records oldest first, skips tenants at their
   `max_runs`, and takes one by compare-and-set. The job carries the package config, the limits,
   the request body, a fresh session token, the provider's shape and path, the gateway URL, and
   signed URLs for the package, the snapshots, the files, and the uploads.
4. **The worker prepares.** The package is unpacked once per digest; the tools layer is built
   once per version and base image by running `install.sh` in a sandbox. The workspace and home
   are restored from snapshots when stale, seeds and files written through `files.write`, the
   prompt and request body placed in the run directory.
5. **The sandbox starts.** `DockerRuntime.start` writes the token and a passwd entry into a
   private directory, creates an internal network, starts the door on it (then connects the door
   to the bridge), and starts the run container: no capabilities, read-only root, the tenant's
   uid and ceilings, the mounts at their own paths, `turn.sh` as the command, the prompt on stdin.
6. **The runner runs the package.** `turn.sh` runs `request.sh` in its own process group with
   stdout teed to a file and relayed, forwards `SIGTERM` to the group and the steer signal to the
   script alone, then runs `response.sh` with the exit code and outcome.
7. **Provider calls go through the gateway.** The CLI calls `hi-provider:8080`; the door forwards
   bytes to the gateway; the gateway resolves the token, checks the path against the shape,
   decrypts the key, relays over TLS, counts the call, and keeps the capture.
8. **Output flows back.** The worker posts chunk records every quarter second; the API's follower
   emits them as deltas; a detail read assembles them. Heartbeats carry cancels and steers back.
9. **The turn ends.** The worker reads the response and streams through `files.read`, uploads the
   door log and the snapshots, and posts the result. `Sessions.result` maps the outcome to a
   status, caps the output, records usage, moves the session's snapshot pointer, and traces the
   response. Teardown removes the container, the door, the network and the token.

## Roles

`api` and `gateway` are stateless over records and blobs and hold the master key. `worker` holds
a credential and caches. `all` runs the three in one process. Followers of a running turn poll
chunk records, so any `api` replica serves any stream.

## Records and blobs

Records are one table: `(kind, tenant, key, doc)`, the doc a JSON object, on SQLite or Postgres
with the same statements. The turn queue is a compare-and-set on a record's status; there is no
broker. Blobs are keys under `tenants/<tenant>/…` in a directory or an S3 bucket; workers reach
them through signed URLs good for one object for a short while.

## Tests

Sixty unit tests run on both record backends and both blob backends (Postgres and an S3
stand-in as services), three Docker tests run a real sandbox, and the layer rule is a test. The
[security](security.md) page maps each promise to its test.

## Repository

```
harness_interface/   the package
catalog/             the twenty-two shipped packages and the template
console/             the console, one HTML file
docs/                this documentation (mkdocs.yml at the root builds it into the wheel)
deploy/              Dockerfile, compose, Caddyfile, cloud-init
scripts/             live.py (the nine checks), demo.py (a recorded turn), catalog_verify.py
tests/               the suite
skills/              a setup skill for coding agents
```
