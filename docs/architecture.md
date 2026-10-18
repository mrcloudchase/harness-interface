# Architecture

How harness-interface works inside: the pieces, the life of a request, the sandbox, where data
lives, how the code is laid out, and how it is verified. For the HTTP surface itself, see
[api.md](api.md).

## The idea

A harness is a program you can start from a shell and hand a task to. Every one has its own
flags, output format, key handling and way of resuming. harness-interface keeps all of that out
of the server:

- **The server knows the contract, not the harnesses.** It hands every harness the same inputs,
  and reads back the same outputs ([api.md](api.md#the-harness-contract)). Everything specific to
  a CLI lives in that harness's own folder: a `harness.json` and a run script.
- **Everything is a resource.** Providers, sandboxes and harnesses are added, changed and removed
  over the API, and each change applies to the next request. Nothing needs a restart.
- **Runs belong to the server.** A request starts a run and the server owns it from then on.
  Clients follow its output, and can leave, come back, or cancel it.
- **Every run is sandboxed.** With the Docker runtime, each run is a fresh container whose only
  way out is a tunnel to its provider.

## The pieces

```
  hi (CLI) ─┐                                   ┌──────────────── Docker ───────────────────┐
  curl ─────┼─► HTTP API ─► ResponseService ─►  │ harness-net-{id} (internal)               │
  any client┘   (app.py)    (responses.py)      │  ┌──────────────┐    ┌──────────────────┐ │
                    │             │             │  │ harness-run  │───►│ harness-door     │─┼─► provider
                    ▼             ▼             │  │ the CLI      │    │ CONNECT allowlist│ │   host only
                Resources     Runtime ──────────┤  └──────────────┘    └──────────────────┘ │
               (registry.py)  docker.py         └───────────────────────────────────────────┘
                    │         local.py ──────────► or a plain process on the host
                    ▼             │
               JSON files     Workspace (git) ─── one per conversation
```

| Piece | Module | Job |
|---|---|---|
| HTTP API | `app.py` | validates requests, calls the service, shapes replies; `main()` starts the server |
| Resources | `registry.py`, `store.py` | providers, sandboxes and harnesses as JSON files; the built-in `default` sandbox |
| ResponseService | `responses.py` | one response end to end: start, run in the background, follow, cancel, recover after a restart |
| Harness contract | `runner.py`, `template.py` | writes the inputs a harness gets, and reads back what it reports |
| Workspace | `workspace.py` | a conversation's directory, a git repository; produced files are what git sees change |
| Runtime | `runtime.py`, `docker.py`, `local.py` | where a harness runs: a sandboxed container, or a local process |
| Egress door | `egress.py` | the only way out of a sandbox: a tunnel to allowlisted hosts |
| CLI | `frontend/cli/hi_cli/` | `hi`, a client of the API and nothing else |

## Life of a request

What happens on `POST /responses`, in order:
- **Steps 1–5 happen inside the request.** A problem there is an HTTP error.
- **Steps 6–10 are the run**, a background task the server owns. A problem there is recorded on
  the response.

1. **Resolve.** Look up the harness named by `model`, then its provider, then its sandbox. With
   `previous_response_id`, load that record and check it was made on the same harness.
2. **Record.** Create the response, `in_progress`.
   - Its workspace is the previous response's, or a new `workspaces/{id}`.
   - Its session id is the previous response's.
   - If that workspace already has a run in progress, answer 409.
3. **Workspace.** Create the directory. On first use, `git init` it, and ignore the internal
   paths (`.hi/`, `.home/`).
4. **Prepare.**
   - Write the request's input files and the harness's templated `files`.
   - Write the request to `.hi/request.json`.
   - Build the environment: the `HI_*` variables plus the harness's `run.env`.
5. **Baseline.** Commit the workspace, so only what the harness itself writes counts as
   produced. Steps 3–5 run in a worker thread, so a large workspace never holds up other
   clients. Then save the record, start the run in the background, and answer: a streaming
   client gets `response.created` at once.
6. **Image.** The tag is `harness-interface/{sandbox}:{sha256 of the Dockerfile}`. If it
   exists, use it. Otherwise build it, one build per tag at a time.
7. **Network and door.** Stop here if the run was cancelled during the build.
   - Hand the workspace to uid 1000.
   - Create the internal network `harness-net-{id}`.
   - Start the egress door `harness-door-{id}` on it, and connect the door alone to Docker's bridge.
   - Wait until the door is listening.
8. **Run.** Start the container `harness-run-{id}` with the hardening below:
   - the workspace at `/workspace`;
   - the scripts read-only at `/harness`;
   - `HTTPS_PROXY` pointing at the door;
   - the environment passed by name, so keys never appear on a command line;
   - the request on stdin.

   The timeout clock starts. If anything in steps 6–8 fails, everything is removed and the
   record ends `failed` with `setup_failed`.
9. **Pump.** Keep stdout byte for byte in `logs/{id}.out`, and hand each line to whoever is
   following the run. A streaming client sends it on as `harness.output`.
10. **Finish.**
    - Wait for the exit, then remove the container, door and network.
    - Read `.hi/output.json`. The status is timeout or cancel first, then the reported
      `status`, then the exit code.
    - Fold the answer, usage, cost and session into the record.
    - List the produced files, and commit the workspace.
    - Save the record, free the conversation, and send `response.completed`.

With the local runtime, steps 6–8 are a plain process in the workspace directory, with the same
environment and stdin, killed by process group on timeout or cancel.

## Runs, many at once

- **Side by side.** Every run is its own background task, its own workspace and, on Docker, its
  own network. Many clients and conversations run at once. Blocking work (git, the workspace
  hand-over) runs in worker threads.
- **One at a time per conversation.** A conversation's workspace holds one run. A second request
  on it gets a 409 until the first finishes.
- **Clients come and go.** A client that disconnects only stops following. The run finishes and
  is recorded either way.
- **Cancel.** Cancel works at any point and from any thread: during setup the harness never
  starts, and while running it is killed.
- **Restart recovery.** At startup:
  - every record still `in_progress` ends `failed`, with `server_restarted`;
  - the Docker runtime removes the containers and networks those runs left.

## The sandbox

Every Docker run gets the same hardening, whatever its sandbox's Dockerfile:

| Control | Setting |
|---|---|
| Privileges | all capabilities dropped; `no-new-privileges` |
| Filesystem | read-only root; a 512 MB tmpfs at `/tmp` that allows exec, because CLIs unpack native modules there |
| Limits | 512 processes, 4 GB memory |
| User | uid 1000, which owns the workspace |
| Network | an internal network of its own, with no route to the internet, the host or other runs |

The **egress door** (`egress.py`) is the run's only way out:
- It is a CONNECT-only tunnel. Its allowlist is the provider's host and port, plus any hosts the
  sandbox names in `egress`.
- It resolves names itself, so the sandbox has no DNS.
- TLS stays end to end, so the door sees nothing it carries.
- Everything else gets a 403: other hosts, other ports, plain HTTP, and requests aimed at the
  door itself.
- The door itself runs with every capability dropped and a read-only root.

A harness can call its model and nothing else, and the door can't be used for anything but that.

The **default sandbox** (`harness_interface/default.Dockerfile`) is one image with the CLI of
every shipped harness, pinned where their publishers allow. It is built once, on the first run
that needs it, about 10 GB, and every run after that is a fresh container from it.

## Data

Everything lives under `HI_DATA_DIR`, by default `~/.harness-interface/data`:

```
providers/{name}.json        the keys: files mode 600, in a mode 700 directory
sandboxes/{name}.json
harnesses/{name}.json
scripts/{harness}/           a harness's scripts, mounted read-only into its runs
responses/{id}.json          the records, written whole (by rename) so a reader never sees half of one
logs/{id}.out, {id}.log      each run's stdout and stderr; build-*.log for image builds
workspaces/{id}/             one per conversation, named after its first response; a git repository
```

`hi` keeps its own state beside the data: `server.pid`, `server.log` and `last-response`, the
response `hi run -c` continues.

## Code layout

```
install.sh              the installer: git check, uv, then this package
harness_interface/      the server
  app.py                routes, startup checks, main()
  config.py             settings from the environment; where each file lives
  errors.py             refusals, and the HTTP status of each
  models.py             Provider, Sandbox, Harness, the request, the Response record
  registry.py           the three resources; the built-in default sandbox
  responses.py          a response end to end, and the runs in flight
  runner.py             the harness contract: inputs in, output.json back
  runtime.py            the Runtime interface, a running Process, spawning one
  docker.py             the Docker runtime: image, network, door, run, teardown, recovery
  local.py              the local runtime
  egress.py             the door
  workspace.py          a conversation's directory, its git baseline, produced files
  store.py              one JsonStore for the four stores
  template.py           {name} placeholders
  default.Dockerfile    the default sandbox
frontend/cli/hi_cli/    hi: main.py (commands), api.py (one method per endpoint),
                        harness.py (folder → PUT body), daemon.py (background server)
harnesses/              the 23 shipped harnesses, one folder each; packaged for `hi harness add --builtin`
tests/                  the API through an echo harness, runs against a real server, the CLI, the door
```

The CLI never imports the server; a test checks that. Anything `hi` can do, any other client can
do through the API.

## Trust

- **Single tenant.** The API binds to localhost and has no authentication; keep it there.
- **Keys.** Provider keys are stored as mode-600 files. They enter a run only as environment
  variables inside its container, and are never returned by the API.
- **Harnesses are your code.** A harness is code you chose to run. The sandbox limits what it can
  reach, not what it does to its own workspace.

## How it is verified

**Tests** (`uv run --extra dev pytest`, no Docker or keys needed). They cover every endpoint
through an echo harness, plus, against a real server:
- streams a client leaves mid-run;
- cancel while running and during setup;
- one run per conversation;
- runs side by side;
- restart recovery;
- the CLI end to end.

They also cover the Docker command lines, image tagging, the wait for the door, and the door
itself.

**Live, on Docker, installed with `curl | sh`:**
- **All 23 shipped harnesses**, each driven only through `hi`:
  - turn one: remember a word and answer `17 * 23`;
  - turn two, with `hi run -c`: recall the word.

  All 23 answered and recalled it, running six at a time.
- **A probe inside a live run** found:
  - no capabilities, no DNS, and no direct way out;
  - no access to the Docker host;
  - `/etc` and `/usr` read-only;
  - through the door, only the provider's host, from the run's first instant.
- **Run handling:**
  - a disconnected client's run still completed;
  - cancel and Ctrl-C killed the run and removed its container, door and network;
  - a busy conversation answered 409;
  - a server killed mid-run was cleaned up on its next start.
- **A bare Debian machine:**
  - the installer stopped without git, then installed with it;
  - `hi` ran the whole flow on the local runtime.
