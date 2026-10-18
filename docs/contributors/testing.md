# Testing

The code was written from these tests, layer by layer, bottom up. Each layer's suite states what
that layer promises, in its docstring and in its test names, and proves it with nothing above that
layer. When a promise changes, its test changes first.

## What each suite proves

| Suite | Layer | Proves |
|---|---|---|
| `test_layers.py` | all | imports point only down; layers 0 to 6 use only the standard library; the public API excludes `api/`; `hi` never imports the server |
| `test_execution.py` | 0 | a `Spec` can't be built wrong or changed; an `Outcome` is exactly one of four; a failure to start is an execution |
| `test_runtimes.py` | 1 | a process streams exactly what it writes, as it writes it; input, timeouts and cancel from any thread work; nothing is left running. The Docker runtime hardens every run, keeps secrets off the command line, builds each image once, and leaves nothing behind on any path; recovery removes only what runs left. The egress door tunnels only the allowed hosts |
| `test_docker_live.py` | 1 | the same promises inside a real container: no capabilities, a read-only root, the right user, only the allowed host reachable, nothing left after a cancel. `-m docker` |
| `test_workspace.py` | 2 | every change is tracked; any file reads as any snapshot left it; paths can't escape; internal paths never show, whatever a project's `.gitignore` says |
| `test_harness.py` | 3 | a harness is given exactly the contract; the key reaches only the environment; refusals happen before anything runs; only this turn's report counts; how a turn ended decides before what it reported; every shipped harness loads and prepares; a turn runs, continues, fails, times out and cancels |
| `test_resources.py` | 4 | names follow the rule; keys are stored for their owner only; writes are whole; `default` is built in and reserved; resolving names whatever is missing |
| `test_routing.py` | 5 | a request names its harness; a conversation stays on its harness |
| `test_platform.py` | 6 | a turn is recorded end to end; a conversation continues in its workspace and session, one turn at a time; turns outlive followers; cancel works at any point; a failed setup and a failed harness are told apart; a restart closes what was in flight |
| `test_api.py` | 7 | every endpoint and error as documented; the Responses shape and its SSE framing; runs outlive clients, run side by side and cancel; the diff is live; the OpenAI SDK works unchanged |
| `test_cli.py` | 8 | `hi` end to end against a real server: add, run, continue, read, a failed run's exit code, the server's lifecycle |
| `test_examples.py` | — | the library example runs, twice, continuing its session |
| `test_release.py` | — | the version has CHANGELOG notes, and the server reports it |

## The stand-ins

Tests need no Docker, no keys and no network. Three stand-ins make that possible:
- **`tests/echo/`**, a harness that echoes its task and what it was given, writes a file,
  reports a session and puts the request's instructions in `AGENTS.md`. Every layer from 3 up
  runs it. A test that needs a harness to fail, hang or print to stderr registers the echo
  harness with another `run.sh`, one line of shell.
- **`tests/fakes/docker`**, an executable that stands in for the Docker CLI. It records every call
  and runs a container's command as a plain process. Files in its state directory turn on failures:
  a failed build, a slow build, a dead door, leftovers to recover. `FakeDocker` in
  `test_runtimes.py` puts it on `PATH`.
- **`LocalRuntime`**, which every test above layer 1 uses, so platform and API tests run real
  processes in real git workspaces.

Fixtures in `conftest.py` give the API and CLI tests a server on the local runtime, in a
throwaway data directory, with the echo harness registered. Use `client` (a FastAPI test client)
for request and response. Use `live` (uvicorn on a real port) for anything a test client can't
show: a stream still running, a client that leaves, requests at the same time.

## Writing a test

- **Put it in the lowest layer that can prove it.** A bug in how a workspace lists files is a
  `test_workspace.py` test, even if you found it through the API.
- **Name the promise, not the function.** `test_cancel_after_the_end_changes_nothing`, not
  `test_cancel_2`.
- **Test the negative space.** What must never happen is as much a promise as what must: a key on
  a command line, a container left after a cancel, an internal path in a listing, a second turn in
  a busy conversation. Each has a test.
- **Wait on events, not time.** Wait for a file to appear, a line to print or a status to change,
  with a deadline. Never sleep a fixed time and hope.
- **No new fakes without need.** A real process in a temporary directory is usually enough.

## Live checks

Some things only a real harness on a real provider can show. Before a release that touches the
Docker runtime, the contract, a shipped harness or the default sandbox, run these by hand, with
your own keys:

1. Install the candidate as users will: `HI_REF=<branch> sh install.sh`.
2. Every shipped harness, two turns, through `hi`, with instructions:
   ```bash
   hi run NAME "Remember the word ORCHID. Reply OK." --instructions "End every answer with PELICAN."
   hi run NAME "Which word did I ask you to remember?" -c --instructions "End every answer with PELICAN."
   ```
   Each must answer both, recall ORCHID, and end both with PELICAN. A harness on a provider you
   have no key for can run on another that speaks its API
   ([providers](../users/providers.md)).
3. **The sandbox, from inside a run.** Register a harness that runs a probe script. The provider
   must be reachable; any other host, and DNS, must fail.
4. **Run handling:** a client that disconnects mid-run (the run still completes), Ctrl-C (nothing
   left in `docker ps -a` or `docker network ls`), a busy conversation (409), and the server killed
   mid-run (its next start fails the record with `server_restarted` and removes the containers).

Note in the pull request what you ran and what passed.
