# Architecture

How harness-interface works inside, and why it is built this way.

## Principles

- **The server knows the contract, not the harnesses.** It gives every harness the same inputs,
  and reads back the same outputs ([contract](../reference/harness-contract.md)). Everything
  specific to a CLI lives in that harness's folder. Adding a harness never changes the server.
- **Everything is a resource.** Providers, sandboxes and harnesses are added, changed and removed
  over the API, and each change applies to the next request. Nothing needs a restart.
- **Runs belong to the server.** A request starts a run, and the server owns it from then on.
  Clients follow its output, and can leave, come back, or cancel it.
- **Sandboxed by default.** With the Docker runtime, each run is a fresh container whose only way
  out is a tunnel to its provider ([security](security.md)).
- **One wire format.** Requests and records use the OpenAI Responses shape, so existing clients,
  including the OpenAI SDK, work unchanged.

## The pieces

```
  hi ───────┐                                   ┌──────────────── Docker ───────────────────┐
  curl ─────┼─► HTTP API ─► ResponseService ─►  │ harness-net-{id} (internal)               │
  OpenAI SDK┘   (app.py)    (responses.py)      │  ┌──────────────┐    ┌──────────────────┐ │
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
| HTTP API | `app.py` | validates requests, calls the service, shapes replies; the startup checks; `main()` |
| Resources | `registry.py`, `store.py` | providers, sandboxes and harnesses as JSON files; the built-in `default` sandbox |
| Response service | `responses.py` | a response end to end: start, run in the background, follow, cancel, recover after a restart |
| Harness contract | `runner.py`, `template.py` | writes what a harness gets, and reads back what it reports |
| Workspace | `workspace.py` | a conversation's directory, a git repository; produced files are what git sees change |
| Runtimes | `runtime.py`, `docker.py`, `local.py` | where a harness runs: a sandboxed container, or a local process |
| Egress door | `egress.py` | the only way out of a sandbox |
| CLI | `frontend/cli/hi_cli/` | `hi`, a client of the API and nothing else |

## The life of a request

What happens on `POST /responses`:
- **Steps 1–5 happen inside the request.** A problem there is an HTTP error.
- **Steps 6–10 are the run**, a background task the server owns. A problem there is recorded on
  the response.

1. **Resolve.** Look up the harness named by `model`, then its provider and its sandbox. With
   `previous_response_id`, load that response and check it was made on the same harness.
2. **Record.** Create the response, `in_progress`.
   - Its workspace is the previous response's, or a new one.
   - Its session id is the previous response's.
   - If the workspace already has a run in flight, answer 409.
3. **Workspace.** Create the directory. On first use, `git init` it, and ignore the internal
   paths.
4. **Prepare.**
   - Write the request's input files and the harness's templated `files`.
   - Write the request to `.hi/request.json`.
   - Build the environment: the `HI_*` variables, plus the harness's `run.env`.
5. **Baseline.** Commit the workspace, so only what the harness writes counts as produced. Steps
   3–5 run in a worker thread, so a large workspace never holds up other clients. Then save the
   record, start the run in the background, and answer: a streaming client gets
   `response.created` at once.
6. **Image.** The tag is `harness-interface/{sandbox}:{hash of the Dockerfile}`. Use it if it
   exists, or build it. Only one build of a tag runs at a time.
7. **Network and door.** Stop here if the run was cancelled during the build.
   - Hand the workspace to uid 1000.
   - Create the run's internal network.
   - Start the egress door on it, and connect only the door to Docker's bridge.
   - Wait until the door is listening.
8. **Run.** Start the harness's container with the hardening on:
   - the workspace at `/workspace`;
   - the scripts read-only at `/harness`;
   - `HTTPS_PROXY` set to the door;
   - its environment passed by name, so keys never appear on a command line;
   - the request on stdin.

   The timeout clock starts. If anything in steps 6–8 fails, everything is removed, and the
   record ends `failed` with `setup_failed`.
9. **Pump.** Keep stdout byte for byte, and hand each line to whoever is following the run.
10. **Finish.**
    - Wait for the exit, then remove the container, the door and the network.
    - Read what the harness reported. The status is timeout or cancel first, then the reported
      status, then the exit code.
    - List the produced files, and commit the workspace.
    - Save the record, free the conversation, and send `response.completed`.

On the local runtime, steps 6–8 are a plain process in the workspace directory, with the same
environment and stdin. A timeout or cancel kills its whole process group.

## Many runs at once

- **Side by side.** Each run is its own background task, its own workspace and, on Docker, its
  own network. Blocking work (git, handing the workspace over) runs in worker threads, so one
  big workspace never stalls the others.
- **One at a time per conversation.** A second request on a busy conversation gets a 409 until
  the first finishes.
- **Clients come and go.** A client that disconnects only stops following. The run finishes and
  is recorded either way.
- **Cancel.** Cancel works at any point, from any thread: during setup the harness never starts,
  and while running it is killed.
- **Restart recovery.** At startup:
  - every record still `in_progress` ends `failed`, with `server_restarted`;
  - the Docker runtime removes the containers and networks those runs left.
- **Whole records.** Records are written by rename, so a reader never sees half of one.

## Code layout

```
install.sh              the installer: git check, uv, then this package
harness_interface/      the server, about 1,200 lines
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
  egress.py             the egress door
  workspace.py          a conversation's directory, its git baseline, produced files
  store.py              one JsonStore for the four stores
  template.py           {name} placeholders
  default.Dockerfile    the default sandbox
frontend/cli/hi_cli/    hi: main.py (commands), api.py (one method per endpoint),
                        harness.py (folder → PUT body), daemon.py (the background server)
harnesses/              the 23 shipped harnesses; packaged for `hi harness add --builtin`
tests/                  the API, runs against a real server, the CLI, the Docker command lines, the door
```

The CLI never imports the server, and a test checks that it doesn't. Anything `hi` does, any
client can do through the API.

## How it is verified

**Tests:** `uv run --extra dev pytest`, with no Docker or keys needed. They cover:
- every endpoint, through an echo harness;
- runs against a real server: a client leaving mid-run, cancel while running and during setup,
  one run per conversation, runs side by side, restart recovery, and the CLI end to end;
- the Docker command lines, image tagging, the wait for the door, and the door itself.

**Live, on Docker, installed with `curl | sh`:**
- **All 23 shipped harnesses**, driven only through `hi`, answered a first request and recalled it
  on a continued second one, six at a time.
- **A probe inside a live run** confirmed the sandbox: only the provider's host was reachable.
- **Run handling:**
  - a disconnected client's run still completed;
  - cancel and Ctrl-C removed everything the run created;
  - a busy conversation answered 409;
  - a server killed mid-run was cleaned up on its next start.
- **A bare Debian machine:** the installer stopped without git, installed with it, and `hi` ran
  the whole flow.
