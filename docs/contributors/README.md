# Contributing to harness-interface

These docs are for changing harness-interface itself: the library, the server, the shipped harness
folders, and how it is tested and released. To use it, see [docs/users](../users/README.md).

**Start here:** read [Architecture](architecture.md), then set up with [Development](development.md).
Every module opens by saying which layer it is in and what it promises.

| | |
|---|---|
| [Architecture](architecture.md) | the layers and their rules, every file, the life of a response, interrupts and stops |
| [Development](development.md) | set up, run from source, test, lint, debug a response |
| [Testing](testing.md) | what each suite proves, the stand-ins, how to write a test, the live suite |
| [Extending](extending.md) | where each kind of change goes: a harness folder, a runtime, a front end |
| [Conventions](conventions.md) | the principles, errors, data, concurrency, secrets, style and docs |
| [Releasing](releasing.md) | versions, the changelog, and how a merge becomes a tagged release |
| [Harness survey](harness-survey/README.md) | how 23 coding CLIs take a task, load config, resume, steer and stop |

## The shortest path to a pull request

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
git switch -c my-change
uv run --extra dev pytest                      # green before you start
# … write the test, then the change …
uv run --extra dev pytest && uvx ruff check --select F,E9 --target-version py311 .
```

A new harness is the easiest place to start: it is a folder, not code
([adding one](extending.md#add-a-harness)).

## Before you open it

- [ ] The change is in the layer it belongs to ([extending](extending.md)), and `test_layers.py`
      passes.
- [ ] A test states the promise, including what must never happen, in the lowest layer that can
      prove it.
- [ ] `pytest` and the lint are green. If it touches the Docker runtime, so is `pytest -m docker`.
- [ ] If it touches a runtime, the contract, `hi_adapter.py`, the base image or a shipped folder, the
      [live suite](testing.md#the-live-suite) passed, and the PR says so.
- [ ] [docs/users](../users/README.md) says what a user now sees; these docs what a contributor needs.
- [ ] `CHANGELOG.md` has a new section for any change in behaviour ([releasing](releasing.md)).
- [ ] No key, token or private URL anywhere in the diff.

## Reporting a problem

Open an [issue](https://github.com/mrcloudchase/harness-interface/issues) with what you ran, what you
expected and what happened: the response's `error` and `harness.stderr` usually say enough. Remove any
key first. For a security problem, don't open an issue; follow [Security](../users/security.md#reporting).
