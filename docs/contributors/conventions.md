# Conventions

The code is small on purpose. These rules keep it that way.

## Principles

- **Keep it simple.** The plainest code that keeps the promise. No option, hook or abstraction until
  something needs it.
- **Say each thing once.** The contract in `contract.py` and `folder.py`, the wire format in `wire.py`,
  the version in `CHANGELOG.md`. Everything else refers to them.
- **One job per module.** Each module's docstring says what it is for. If a change makes that untrue,
  the change belongs elsewhere.
- **Objects for state and identity, functions for the rest.** `Sessions`, `Response`, `Workspace` are
  classes; `prepare`, `collect`, `parse_model` are functions.
- **Negative space.** Decide what can't happen, make it impossible, and test that. A `Spec` can't be
  built with an empty command. A key can't reach a command line. A response can't be left in progress.
  A session can't run two responses at once.
- **Test first.** The test states the promise; then the code keeps it.

## Errors

| | Raise | Becomes |
|---|---|---|
| The caller asked for something that can't be done | `Invalid` | 400 |
| It names something that doesn't exist | `NotFound` | 404 |
| It conflicts with what is happening now | `Conflict` | 409 |
| Something stopped a run starting | nothing: return `NeverStarted(reason)` | `failed`, `failed_to_start` |
| A harness failed | nothing: it is a `Result` | `failed`, `harness_failed` |
| A bug | let it raise | `failed`, `internal_error` |

- Refuse early, before anything runs or is written, and name every problem at once where you can
  (`folder_problems`).
- A message says what was wrong and what to do: "no provider for codex: register one for
  https://api.openai.com/v1 (openai-responses), or name one", not "invalid provider".
- Catch `Exception` only where something must still end whatever went wrong: a response's record, a
  socket in the door.

## Data

- Values are frozen dataclasses, validated in `__post_init__`, so nothing invalid exists. `Session`
  and `ResponseRecord` are the mutable ones: the state of what is running.
- Records are one JSON file each, written whole (temp file, then rename).

## Concurrency

- Everything is asyncio. Blocking work (git, copying a folder) goes through `asyncio.to_thread`.
- Anything cancelled from another thread goes through `loop.call_soon_threadsafe`.
- Cleanup that must happen is shielded. Teardown runs on every path, a cancel during setup included.
- A reader's speed never decides a writer's: output is pumped as it arrives, whether or not anyone
  follows.

## Secrets

- A key lives in its provider's file (mode 600, in a 700 directory), in memory, in the door's stdin, and,
  in file mode, in a credential file the run mounts read-only. Nowhere else.
- Environment values go by name (`docker run -e NAME`), never on a command line.
- Never log, record, return or print a key. `ProviderEntry.key` is `repr=False`; nothing served
  includes it.
- Tests use plainly fake keys. Never commit a real one.

## Style

- Module docstrings first: the layer, what the module is for, what it promises. Function docstrings
  say what and why.
- Comments are rare, explain a reason the code can't show, and sit at the end of the line they explain.
- Names say what something is in the domain: `session`, `response`, `folder`, `workspace`.
- `from __future__ import annotations` everywhere but `api/app.py`, where FastAPI reads the types.
- Lines up to about 120 characters. No formatter: match what's around you.
- Delete what isn't used. No commented-out code, no `TODO`s.

## Documentation

A change that changes behaviour updates [docs/users](../users/README.md) for what a user sees, these
docs for what a contributor needs, and `CHANGELOG.md` ([releasing](releasing.md)). Users' docs say what
to do, then what happens, with a real example.

## Commits and pull requests

- One change per pull request, on its own branch, with its tests and docs.
- The commit message says what changed and why, in the present tense: `area: summary`.
- CI must be green: the tests on Python 3.11, 3.13 and 3.14, the Docker tests, and the lint.
