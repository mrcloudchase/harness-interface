# AGENTS.md

Read this before changing anything here. It says what harness-interface is for, the principles
every change must keep, how a request flows through the code, and where each kind of change
goes. The full detail is in [docs/contributors](docs/contributors/README.md) and
[docs/users](docs/users/README.md); this file points there rather than repeat them.

## What this is

harness-interface is an execution layer for coding harnesses. A client asks for a turn; the
server runs the harness that request names in a sandbox, streams its output, and keeps a record
of what it did. People reach it three ways, for three audiences: `hi` from a terminal, an OpenAI
Responses-compatible HTTP API from any language or the OpenAI SDK, and a Python library with no
server. With those they build agents, loops and workflows on top of whichever harness fits.

**We don't manage harness protocol; we manage the execution layer.**

## Keeper runs this repository

Coding agents build and maintain this project through Keeper ([the spec](docs/keeper-spec.md)),
which runs entirely in this repository's GitHub Actions. The human owner steers with
[VISION.md](VISION.md) and approves only the human tier; everything else is planned, built,
reviewed, merged and released by Keeper's jobs, prompts and loops.

- **Every task serves a theme in `VISION.md`.** A Keeper PR names it in a `Theme:` trailer.
- **The human tier** (`[tiers]` in [keeper.toml](keeper.toml)) is the vision, this file, Keeper's
  engine, tests and configuration, the workflows, and the execution layer: `execution.py`,
  `runtimes/`, `harness/contract.py`, `default.Dockerfile`. A change there waits for the owner.
- **Keeper's gate decides what merges:** every `[checks]` command, tests that only grow, the size
  budget, `area: summary` titles, and the loop's verdict on that exact commit.
- **If you are an agent working for Keeper,** your role's prompt says what to do and the workflow
  does the rest: you never push, merge or open anything yourself.

## Founding principles

Every change keeps all five. A change that needs to break one is the wrong change.

1. **One interface, many ways in.** A request to any harness has one shape: `model` names the
   harness, `previous_response_id` continues its conversation, and the answer comes back whole or
   streamed. `hi`, the API and the library run a harness the same way, because the first two are
   built on the third.
2. **Harnesses live outside the server.** A harness is a folder (`harness.json`, a `run.sh`, a
   `report.py`, an `artifacts` file), not code. The server has no code for any particular harness:
   no branch on a harness's name, no CLI flag, no output format. The 23 folders in `harnesses/`
   are templates users copy and change, not part of the platform.
3. **Harness agnostic, with a minimal contract that is closed.** The execution layer doesn't
   care that it runs a harness. The one thing it knows of any harness, now or in the future, is
   that it takes input and returns output. So it gives the program its inputs (`HI_*` variables,
   the request on stdin and in `.hi/request.json`, files in its workspace) and returns its outputs
   (stdout, stderr, the workspace's changes, and an optional JSON report at `HI_OUTPUT`) to the
   client, streamed or not. Nothing more. The contract lives in one place,
   `harness_interface/harness/contract.py`, and it is **never extended**: no new variable,
   placeholder, `harness.json` field or reported key, and nothing removed or renamed. Whatever a
   harness needs beyond it, its own folder builds from what it already gets. That is what keeps
   the server ready for any harness, however harnesses work today or later.
4. **Harness configuration is infrastructure users bring.** Providers, sandboxes and harnesses are
   resources a user PUTs, separate from the server, and the next request uses them with no
   restart. How a CLI behaves (permissions, MCP servers, skills, hooks, settings) is the harness
   author's choice, carried in the folder's `artifacts`, `files` or `run.sh`. The server reads
   none of it and ships no defaults for it.
5. **Strict sandbox by default, overridable by the user.** Every Docker run gets a fresh container
   from its sandbox's image: no capabilities, no privilege escalation, a read-only root, a
   non-root user, process and memory limits, and an internal network whose only way out is the
   egress door. The door is CONNECT-only and allows exactly the provider's `host:port` plus the
   sandbox's `egress` list. The built-in `default` sandbox can't be replaced; a user adds their
   own Dockerfile and egress list under another name. The hardening on `docker run` applies
   whatever the Dockerfile says.

## How it is built

The package is about 1,900 lines of Python in layers. Each layer imports only from layers below
it; `tests/test_layers.py` enforces that, that layers 0 to 6 use only the standard library, and
that `hi` never imports the server.

| | Layer | Where | What it knows |
|---|---|---|---|
| 0 | execution | `errors.py`, `execution.py` | `Spec` in, `Event`s out, one `Outcome`; `NeverStarted`; `Invalid`, `NotFound`, `Conflict` |
| 1 | runtimes | `runtimes/` | `ProcessExecution` (the only code that spawns a process), `LocalRuntime`, `DockerRuntime`, `Docker`, `Sandbox`, the egress door |
| 2 | workspace | `workspace.py` | a working directory as a git repository: snapshots, changes, diffs, files; internal paths hidden |
| 3 | harness | `harness/` | the contract (`prepare`, `collect`), `{name}` templating, one `Turn` on any runtime |
| 4 | resources | `resources/` | `JsonStore`, `Registry`, the built-in `default` sandbox and its Dockerfile |
| 5 | routing | `routing.py` | which harness serves a request: `ByName` |
| 6 | platform | `platform/` | `Service`, `Record`, `Run`, `Placement`: turns in the background, conversations, cancel, recovery |
| 7 | front end | `api/` | the Responses wire format (`wire.py`), routes (`app.py`), settings (`config.py`) |
| 8 | client | `frontend/cli/hi_cli/` | `hi`: HTTP calls only, plus starting and stopping the server |

`harness_interface/__init__.py` is the library's public API: layers 0 to 3, nothing from `api/`.
Every module opens with a docstring naming its layer and its promise. Read it first, and keep it
true.

## The flow of a turn

```
POST /responses
  wire.ResponseRequest.ask()                     the only place the Responses format is known
  Service.start(ask)
    previous record, if continuing               its workspace, session and harness
    ByName.route(model, previous harness)        "harness" or "harness/model"; a conversation stays on its harness
    Registry.resolve(harness)                    harness + provider + sandbox + scripts dir; anything missing is a 400
    Record(status="running"), workspace busy     a second turn in the same conversation is a 409
    Turn.start(Placement.runtime(resolved), ...)
      Workspace.init, prepare, snapshot "prepare"   request files, harness files, .hi/request.json, Spec with HI_* env
      runtime.start(spec), as a task             Docker: build image once, hand workspace to uid 1000 if root,
                                                 internal network, door, wait for door, docker run -e NAME (values never on argv)
    Service._drive in the background             pump stdout/stderr to logs/{id}.out/.log and to followers
      Turn.result: collect, changes, snapshot "turn"
      Record.finish(result) or fail("internal_error"); always free the workspace
  reply: the finished record, or SSE: response.created, harness.output/harness.log per line, response.completed
```

The turn belongs to the server, not the request: a client that leaves only stops following. At
startup `Service.recover` fails every record still `running` with `server_restarted`, and the
placement removes leftover containers and networks. Full detail:
[architecture](docs/contributors/architecture.md#the-life-of-a-turn).

## Rules that must always hold

All but the first have a test. Keep them; to change one, change its test first and say why.

- No harness-specific code outside `harnesses/`, and nothing added to the contract. A harness
  that needs more builds it in its own folder or its sandbox. Review holds this one: nothing
  tests it.
- A key never reaches a command line, a record, a log or an API response. `Provider.key` is
  `repr=False`; `app.public()` drops it; `docker run -e NAME` passes names only.
- A failure to start is an `Outcome`, not an exception: return `NeverStarted(reason)`. Only a
  caller's mistake raises, as `Invalid`, `NotFound` or `Conflict` (400, 404, 409).
- Output never waits on a reader; `wait()` never depends on anyone iterating events.
- Paths are the same inside the sandbox and out: the workspace and scripts mount at their own paths.
- One turn per conversation. A record is never left `running`.
- `.hi/`, `.home/`, `.git/` and `__pycache__/` are never listed, diffed, committed or served,
  whatever a project's `.gitignore` says.
- `default` is built in: never stored, replaced or deleted.
- Teardown runs on every path, including a cancel during setup, and is shielded.

## Where a change goes

| You want to | Change | Not |
|---|---|---|
| support a new CLI | a folder in `harnesses/` | any Python |
| give a harness a tool or a host | its sandbox: a Dockerfile and `egress` | the runtime |
| add a tool to every shipped harness | `resources/default.Dockerfile`, pinned | |
| run somewhere new | a `Runtime` in `runtimes/` and a `Placement` | the contract or the platform |
| choose harnesses another way | a `Router` in `routing.py` | the platform or the API |
| give a harness something it doesn't get | its folder (`run.sh`, `files`, `artifacts`) or its sandbox | the contract, or a harness-specific branch |
| serve another wire format | a package beside `api/`, calling `Service` | the platform |
| add a command to `hi` | `frontend/cli/hi_cli/` | the server |
| change how Keeper works here | `.keeper/loops/`, `.keeper/prompts/` | `.keeper/engine/`, `keeper.toml` or the workflows, which are the owner's |

If a change seems to need two layers to learn something new, the lower one is missing a general
idea; add that. Full guide: [extending](docs/contributors/extending.md).

### A harness folder

- `harness.json`: `name`, `provider`, `sandbox`, `files` (templated, written before every turn),
  `run` (`argv`, `env`, `stdout` content type, `timeout_s`). Set `"HOME": "{workspace}/.home"` so
  the CLI's state survives between turns and is never listed. Put `{instructions}` where the CLI
  reads them, usually `"files": {"AGENTS.md": "{instructions}"}`.
- `run.sh`: opens with the shared artifacts block, word for word (a test checks every copy is
  identical), maps `HI_PROVIDER_URL`/`HI_PROVIDER_KEY` onto the CLI's own settings, runs it
  headless, resumes with `HI_SESSION_ID`, and pipes into `report.py`. Its opening comment explains
  every setting `harness.json` makes.
- `report.py`: passes every line through unchanged and flushed, then writes `answer`, `status`,
  `session_id`, `usage`, `cost_usd` to `HI_OUTPUT`, whichever the CLI gives.
- `artifacts`: ships with comments only, so it brings nothing until a user adds a line.

To ship a new one: add the folder, pin its CLI in `default.Dockerfile`, add it to the table in
`harnesses/README.md` and the list in `README.md`, raise the count of 23 in
`tests/test_harness.py` and `tests/test_cli.py`, and run it live for two turns with instructions.

## Working here

```bash
uv run --extra dev pytest                                   # everything; no Docker, no keys, under a minute
uv run --extra dev pytest -m docker                         # against a real Docker daemon
uvx ruff check --select F,E9 --target-version py311 .       # CI's lint
HI_DATA_DIR=/tmp/hi-dev uv run --extra server harness-interface   # the server from source, throwaway data
HI_RUNTIME=local uv run --extra server harness-interface    # harnesses as plain processes
```

Tests need no Docker, keys or network: `tests/echo/` is a stand-in harness, `tests/fakes/docker`
stands in for the Docker CLI, and every layer above 1 runs on `LocalRuntime`. CI runs the suite on
Python 3.11, 3.13 and 3.14, the Docker tests and the lint, on every pull request.

## Conventions

- **Keep it simple.** The plainest code that keeps the promise. No option, hook or abstraction
  until something needs it. No dead code, commented-out code or `TODO`s.
- **Say each thing once.** The contract in `contract.py`, the wire format in `wire.py`, the
  version in `CHANGELOG.md`.
- **One job per module.** If a change makes a module's docstring untrue, it belongs elsewhere.
- **Objects for state and identity, functions for the rest.** `Turn`, `Service`, `Workspace` are
  classes; `prepare`, `collect`, `render` are functions.
- **Negative space.** Decide what can't happen, make it impossible, and test that.
- Values are frozen dataclasses, validated in `__post_init__`; `Record` is the one mutable one.
- Everything is asyncio. Blocking work goes through `asyncio.to_thread`; anything cancelled from
  another thread goes through `call_soon_threadsafe`; cleanup that must happen is shielded.
- `from __future__ import annotations` everywhere except `api/app.py`. Lines up to about 120
  characters. No formatter: match the code around you. Comments are rare, explain why, and sit at
  the end of the line they explain.
- A test goes in the lowest layer that can prove the promise, is named for the promise
  (`test_cancel_after_the_end_changes_nothing`), tests what must never happen too, and waits on
  events, never a fixed sleep.

All of it: [conventions](docs/contributors/conventions.md), [testing](docs/contributors/testing.md).

## Before you open a pull request

- [ ] One change, on its own branch, in the layer it belongs to.
- [ ] A test states the promise, including what must never happen.
- [ ] `pytest` and the lint are green; `pytest -m docker` too if it touches the Docker runtime.
- [ ] If it touches the runtime, the contract, a shipped harness or the default sandbox, the
      [live checks](docs/contributors/testing.md#live-checks) ran, and the PR says what passed.
- [ ] `docs/users` says what a user now sees; `docs/contributors` what a contributor needs.
- [ ] For any change in behaviour, `CHANGELOG.md` has a new section at the top, `## [X.Y.Z]`, the
      next version, saying what changed.
- [ ] No key, token or private URL anywhere in the diff.

A release is a new `CHANGELOG.md` section merged to `main`: its heading is the version (the
only place it is written; `pyproject.toml` reads it from there), and `release.yml` tags and
publishes it with the section as its notes. Nobody tags by hand. Removing or
changing anything in the API or the CLI is a major version
([releasing](docs/contributors/releasing.md)).
