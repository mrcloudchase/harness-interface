# Contributing to harness-interface

Welcome. These docs are for changing harness-interface itself: the library, the server, `hi`, the
shipped harnesses, and how it is tested and released. To use it, see [docs/users](../users/README.md).

**Start here:** read [Architecture](architecture.md), then set up with [Development](development.md).
The whole package is about 1,900 lines, and every module opens by saying what it is for.

| | |
|---|---|
| [Architecture](architecture.md) | the layers and their rules, every file and its purpose, the life of a turn, and why it is built this way |
| [Development](development.md) | set up, run from source, test, lint, debug a run |
| [Testing](testing.md) | what each suite proves, the stand-ins, how to write a test, the live checks |
| [Extending](extending.md) | where each kind of change goes: a harness, a runtime, a router, an endpoint, a front end |
| [Conventions](conventions.md) | the principles, errors, data, concurrency, secrets, style and docs |
| [Releasing](releasing.md) | versions, the changelog, and how a merge becomes a tagged release |
| [Keeper](../keeper-spec.md) | how agents build and maintain this repository from VISION.md, and how to port it to another |

## The shortest path to a pull request

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
git switch -c my-change
uv run --extra dev pytest                      # green before you start
# … write the test, then the change …
uv run --extra dev pytest && uvx ruff check --select F,E9 --target-version py311 .
```

New harnesses are the easiest place to start: a harness is a folder, not code
([adding one](extending.md#add-a-harness)).

## Before you open it

- [ ] The change is in the layer it belongs to ([where changes go](extending.md)), and
      `test_layers.py` passes.
- [ ] A test states the promise, including what must never happen, in the lowest layer that can
      prove it.
- [ ] `pytest` and the lint are green. If it touches the Docker runtime, so is `pytest -m docker`.
- [ ] If it touches the runtime, the contract, a shipped harness or the default sandbox, the
      [live checks](testing.md#live-checks) ran, and the PR says what passed.
- [ ] [docs/users](../users/README.md) says what a user now sees; these docs say what a contributor
      now needs to know.
- [ ] `CHANGELOG.md` has a new section, the next version, saying what changed
      ([releasing](releasing.md)); merging it releases it.
- [ ] No key, token or private URL anywhere in the diff.

## Reporting a problem

Open an [issue](https://github.com/mrcloudchase/harness-interface/issues) with what you ran, what
you expected and what happened: the record (`hi show ID`) and the harness's log (`hi log ID`)
usually say enough. Remove any key first. For a security problem, don't open an issue; follow
[Security](../users/security.md#reporting).
