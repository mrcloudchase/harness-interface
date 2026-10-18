# Conventions

The code is small on purpose: about 1,900 lines of Python in the package, readable in an
afternoon. These rules keep it that way.

## Principles

- **Keep it simple.** Write the plainest code that keeps the promise. Don't add an option, a
  hook or an abstraction until something needs it. Every line is something the next contributor
  has to read.
- **Say each thing once.** Each fact has one home: the harness contract in `contract.py`, the
  wire format in `wire.py`, the version in `pyproject.toml`. Everything else refers to it.
- **One job per module, one owner per idea.** Each module docstring says what the module is for.
  If a change makes that sentence untrue, the change belongs somewhere else.
- **Objects for what has state and identity, functions for what doesn't.** `Turn`, `Service` and
  `Workspace` are classes. `prepare`, `collect` and `render` are functions.
- **Negative space.** Decide what can't happen, make it impossible, and test that. A `Spec` can't
  be built with an empty command. A key can't reach a command line. A record can't be left
  `running`. A conversation can't run two turns at once.

## Errors

| | Raise | Becomes |
|---|---|---|
| The caller asked for something that can't be done | `Invalid` | 400 |
| It names something that doesn't exist | `NotFound` | 404 |
| It conflicts with what is happening now | `Conflict` | 409 |
| Something stopped a run starting | nothing: return `NeverStarted(reason)` | a failed outcome, `setup_failed` |
| A harness failed | nothing: it is a `Result` | `failed`, `harness_failed` |
| A bug | let it raise; `assert` what only a bug could break | `internal_error` on the record |

- Refuse early, before anything runs or is written.
- A message says what was wrong and, where it helps, what to do: "sandbox 'x' has an empty
  Dockerfile", not "invalid sandbox".
- Never catch an exception just to log it. Catch `Exception` only where something must still end
  whatever went wrong: a record (`Service._drive`), a socket (the egress door).

## Data

- Values are frozen dataclasses. To change one, build a new one with `dataclasses.replace`. The
  one exception is `Record`, which is the state of a turn and changes as the turn runs.
- Validate in `__post_init__`, so nothing invalid can exist. The API relies on this: a bad body is
  refused as 422 because its dataclass won't build.
- Sequences in a value are tuples. `Spec.env`, the mapping every runtime is handed, is a
  read-only `MappingProxyType`.

## Concurrency

- Everything is asyncio. Slow blocking work (git, `chown` over a whole tree) goes through
  `asyncio.to_thread`, so one big workspace never stalls other runs. FastAPI runs the synchronous
  routes, such as a diff, in its own threads.
- Anything that can be cancelled from another thread goes through `loop.call_soon_threadsafe`.
- Cleanup that must happen even when cancelled is shielded: `asyncio.shield(teardown(...))`.
- Never let a reader's speed decide a writer's. Output is pumped into a queue as it arrives.

## Secrets

- In platform code, a key lives in the provider's JSON file (mode 0600, in a 0700 directory), in
  memory, and in a run's environment, and nowhere else.
- Pass environment values by name (`docker run -e NAME`), never on a command line.
- Never log, record, return or print a key. `Provider.key` is `repr=False`, and the API's
  `public()` drops it.
- A harness may do more with its own key inside its sandbox, such as log its CLI in. That is the
  harness's business, and its folder says so.
- Never commit a real key, even in a test. Tests use plainly fake ones, such as `"k"`.

## Style

- Module docstrings first: the layer, what the module is for, what it promises. Function
  docstrings say what and why, not how.
- Comments are rare and explain a reason the code can't show. Put a short one at the end of the
  line it explains.
- Names say what something is in the domain: `turn`, `record`, `workspace`, not `obj`, `data`,
  `mgr`.
- `from __future__ import annotations` everywhere except `api/app.py`, where FastAPI reads the
  types at runtime.
- Lines up to about 120 characters. No formatter: match what's around you.
- Delete what isn't used. No commented-out code, no `TODO`s in place of work, no code for a
  future that hasn't arrived.

## Documentation

The docs are part of the change. A pull request that changes behaviour updates:
- [docs/users](../users/README.md) for anything a user can see: a command, an endpoint, a field,
  an error, a guarantee;
- these docs for anything a contributor needs: a layer, a rule, a file, a test;
- `CHANGELOG.md`, under `Unreleased`.

Users' docs are written for someone who wants to get something done. Say what to do, then what
happens, with a real example, in plain sentences.

## Commits and pull requests

- One change per pull request, on its own branch, with its tests and docs.
- The commit message says what changed and why, in the present tense.
- CI must be green: the tests on Python 3.11, 3.13 and 3.14, the Docker tests, and the lint.
