# Architecture

Seven layers, each importing only from below. A layer knows nothing of the ones above it.

| Layer | Module | Knows | Does not know |
|---|---|---|---|
| 0 | `execution.py`, `errors.py`, `secrets.py` | what running something means (Spec, Execution, Outcome); sealing a value | processes, containers, harnesses |
| 1 | `runtimes/process.py`, `runtimes/docker.py`, `runtimes/door.py` | a process; a container with an internal network, a door and a gateway | what the command is for |
| 2 | `harness.py` | the folder: `harness.json`, the scripts, the seeds, the digest | where it is stored, who owns it |
| 3 | `store.py` | orgs, members, keys, providers (sealed), sandboxes, harness versions, on disk | running anything |
| 4 | `sandboxes.py` | an image for a sandbox; a tools layer built by `install.sh`; a runtime with the sandbox's limits | sessions |
| 5 | `sessions.py` | a session directory, seeds applied, one turn run and recorded, steer, cancel, trace, archive | HTTP, the wire format |
| 6 | `api/wire.py`, `api/app.py`, `api/config.py`, `__main__.py` | the Responses format; the routes and who may call them; settings | anything a lower layer does |

The server reads three files from a harness folder and copies the rest; the output of a turn is
relayed byte for byte. Those two facts are what keep the harness count at zero in this repository
and the per-CLI code at zero in the server.

## One turn

1. `app.py` resolves the Bearer key to a member and parses the body with `wire.ResponseRequest`,
   which becomes an `Ask`: harness name, prompt, files, overrides, previous response, `store`.
2. `Sessions.create` loads the harness (the session's pinned version when continuing), its config,
   the sandbox and the provider by name under the member's org; refuses a busy session; creates or
   reuses the session directory; applies `seeds/project` (new session), `seeds/user` (first use of
   the member's home), `seeds/org` (every turn); writes the request's files; records the response
   as `in_progress`, appends the request to the trace, and starts `_run` as a task.
3. `_run`, under the org's semaphore: `Runtimes.image_for` pulls or builds the sandbox's image;
   `Runtimes.tools_for` runs `install.sh` once per (harness version, image) and caches the layer;
   `Store.open_key` opens the provider's key; a `DockerRuntime` is built with the folder and tools
   read-only, home and run directory writable, the sandbox's egress and limits, and a `Provider`
   carrying the key and a fresh session token.
4. `DockerRuntime.start`: an internal network, the door container (given the token and key on
   stdin) reaching the bridge, then the run container with `bash request.sh`, the prompt on stdin,
   the variables by name. Its stdout and stderr stream back as events; the door's log goes to the
   session's `door.log`.
5. The feed publishes every chunk to followers (the SSE stream); on exit `_finish` maps the Outcome
   to a status, saves the record, appends it to the trace, and for `store: false` removes the
   workspace and run directory.
6. `wire.response` shapes the record: two messages, the status, the metadata.

A steer writes `run/interrupt` and sends the harness's signal to the container; a cancel calls the
execution's `stop` (SIGTERM, then SIGKILL after the grace).

## Storage

`store.py`'s docstring is the layout. Records are JSON files written whole; harness versions are
folders named by digest with their tools layers beside them; sessions are directories under
`sessions/<org>/<member>/<harness>/`. An `index/` maps response and session ids to their session
directories so `GET` is one read.

## The two deployment shapes

A hosted platform and a self-hosted box run the same code. The admin key and `POST /v1/orgs` are
how a platform creates tenants; `init` is how a box creates its one. Everything after that is a
member's key and an org prefix.
