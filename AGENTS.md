# AGENTS.md

Read this before changing anything here. It says what harness-interface is for, the principles every
change keeps, how a response flows through the code, and where each kind of change goes. The detail is
in [docs/contributors](docs/contributors/README.md) and [docs/users](docs/users/README.md).

## What this is

harness-interface is an execution layer for coding harnesses. A client starts or continues a session;
the server runs the harness it names in a sandbox, with the folder's config and work artifacts in
place, streams what it prints, takes interrupts and stops, and returns everything it produced. It is
reached two ways: an OpenAI Responses-compatible HTTP API with session routes, and the Python library
the server is built on.

**We don't manage harness protocol; we manage the execution layer.** [VISION.md](VISION.md) is the
owner's direction.

## Founding principles

1. **One interface.** `model` names the harness (`harness[@provider][/model]`),
   `previous_response_id` continues its session, interrupt and stop act on a running one, and the
   answer comes back whole or streamed. The API and the library run a harness the same way, because
   the first is built on the second.
2. **Harnesses live outside the server.** A harness is a folder: `harness.json`, `install.sh`,
   `run.sh`, `adapter.py`, `hi_adapter.py`, `home/`, `workspace/`, and optionally `image.Dockerfile`.
   No branch on a harness's name, no CLI flag, no output format in the server.
3. **A minimal, versioned contract.** A harness is given environment variables (`HI_*`, `HOME`,
   `PATH`), line 1 of stdin (`{"task", "resume"}`) and later lines (steers), and gives back stdout,
   stderr, its workspace's changes, the files its `report` globs match under `$HOME`, and one JSON file
   at `HI_OUTPUT`. It lives in `harness/folder.py` and `harness/contract.py`, and changes only as a new
   contract version.
4. **Configuration is something users bring.** Providers and harness folders are resources a user
   puts; the next request uses them. How a CLI behaves is its folder's: the server reads none of it.
5. **Strict sandbox by default.** Every install and response gets a fresh container: no capabilities,
   no privilege escalation, a read-only root, an unprivileged user, limits, and an internal network
   whose only way out is its door: the provider through its gateway, and the hosts the folder names.
   The key stays in the gateway; the run holds a token.

## How it is built

About 3,500 lines of Python, in layers. Each imports only from those below it; `tests/test_layers.py`
enforces that, and that layers 0 to 5 use only the standard library.

| | Layer | Where | What it knows |
|---|---|---|---|
| 0 | execution | `errors.py`, `execution.py` | `Spec` in, `Event`s out, input, stop, kill, one `Outcome`; `NeverStarted`; `Invalid`, `NotFound`, `Conflict` |
| 1 | runtimes | `runtimes/` | `process.py` (the only code that spawns), `LocalRuntime`, `DockerRuntime`, `Images`, the door and gateway |
| 2 | workspace | `workspace.py` | a directory and its history, kept outside it: snapshots, changes, diffs, files; internal paths hidden |
| 3 | harness | `harness/` | `HarnessFolder`, `Installer`, `Placement`, `prepare`/`collect`, `Response`, `hi_adapter.py`, the base image |
| 4 | store | `store.py` | `JsonStore`, `Registry`: providers, and folders with their install state |
| 5 | sessions | `sessions.py` | `Sessions`: start, follow, wait, interrupt, stop, artifacts, recover |
| 6 | server | `api/` | the Responses wire format (`wire.py`), routes (`app.py`), settings (`config.py`) |

`harness_interface/__init__.py` is the library's public API: layers 0 to 5. Every module opens with a
docstring naming its layer and its promise. Read it first, and keep it true.

## The flow of a response

```
POST /responses → wire.ResponseRequest.ask() → Sessions.start(ask)
  parse_model, the previous session (busy: 409), the provider (named, or the folder's default)
  in the background: Registry.ready (install once per version) → Response.start
    prepare: workspace/ on a new session, request files, home/ into .home, files rendered, a snapshot
    Placement.runtime → runtime.start: network, door + gateway, credential, docker run --init, hardened
  _pump: stdout, stderr, door, steers → logs/ and followers
  Response.result → collect: HI_OUTPUT, status, changes, reported artifacts
  the record finished; steers it didn't take sent again if it ended ok
reply: the finished response, or SSE events
```

A response belongs to the server: a client that leaves only stops following. `Sessions.recover` at
startup fails what a restart cut off (`server_restarted`) and sweeps this data directory's leftovers.
Full detail: [architecture](docs/contributors/architecture.md).

## Rules that must always hold

All but the first have a test. To change one, change its test first and say why.

- No harness-specific code outside `harnesses/`. Review holds this one.
- A key never reaches a command line, an environment variable, a record, a log or a response; under
  the gateway it never enters the sandbox.
- A failure to start is an `Outcome` (`NeverStarted`), not an exception. Only a caller's mistake
  raises: `Invalid`, `NotFound`, `Conflict` (400, 404, 409).
- Output never waits on a reader; `wait()` never depends on anyone iterating events.
- Paths are the same inside the sandbox and out.
- One response per session at a time. A response is never left in progress.
- `.home/`, `.git/` and `__pycache__/` are never listed, diffed or served as work; only `report` brings
  files back from `.home/`.
- Every folder's `hi_adapter.py` is byte-identical to `harness_interface/harness/hi_adapter.py`.
- Teardown runs on every path, a cancel during setup included, and is shielded. A sweep removes only
  its own data directory's leftovers.

## Where a change goes

| You want to | Change | Not |
|---|---|---|
| support a new CLI | a folder in `harnesses/` | any Python |
| give a CLI config, a tool or a host | its folder: `home/`, `files`, `install.sh`, `run.egress`, `image.Dockerfile` | the server |
| change what every harness starts from | `harness/base.Dockerfile`, pinned | |
| run somewhere new | a `Runtime` in `runtimes/`, and `Placement` | the contract or sessions |
| serve another wire format | a package beside `api/`, calling `Sessions` | sessions |
| change the contract | a new contract version, with every folder moved | a special case |

Full guide: [extending](docs/contributors/extending.md).

## Working here

```bash
uv run --extra dev pytest                                   # everything; no Docker, keys or network
uv run --extra dev pytest -m docker                         # against a real Docker daemon
uvx ruff check --select F,E9 --target-version py311 .       # CI's lint
HI_DATA_DIR=/tmp/hi-dev uv run --extra server harness-interface   # the server from source
uv run --extra dev python scripts/live.py harnesses/NAME --url … --api … --key-file …   # a folder, live
```

Tests need no Docker, keys or network: the template folder's stand-in CLI runs every layer from 3 up on
this machine, `tests/fakes/docker` stands in for the Docker CLI, and `tests/upstream.py` for a provider.

## Conventions

- **Keep it simple.** The plainest code that keeps the promise. No option or abstraction until
  something needs it. No dead code, commented-out code or `TODO`s.
- **Say each thing once.** The contract in `folder.py` and `contract.py`, the wire format in `wire.py`,
  the version in `CHANGELOG.md`.
- **One job per module.** If a change makes a module's docstring untrue, it belongs elsewhere.
- **Objects for state and identity, functions for the rest.**
- **Negative space.** Decide what can't happen, make it impossible, and test that.
- **Test first**, in the lowest layer that can prove the promise, named for the promise, waiting on
  events, never a fixed sleep.
- Everything is asyncio; blocking work goes through `asyncio.to_thread`; cleanup that must happen is
  shielded. Lines up to about 120 characters; match the code around you.

All of it: [conventions](docs/contributors/conventions.md), [testing](docs/contributors/testing.md).

## Before you open a pull request

- [ ] One change, on its own branch, in the layer it belongs to.
- [ ] A test states the promise, including what must never happen.
- [ ] `pytest` and the lint are green; `pytest -m docker` too if it touches the Docker runtime.
- [ ] If it touches a runtime, the contract, `hi_adapter.py`, the base image or a shipped folder, the
      live suite passed for the folders it affects, and the PR says so.
- [ ] `docs/users` and `docs/contributors` say what changed; `CHANGELOG.md` has a new section for any
      change in behaviour ([releasing](docs/contributors/releasing.md)).
- [ ] No key, token or private URL anywhere in the diff.
