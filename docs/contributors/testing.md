# Testing

The code was written from these tests, layer by layer, bottom up. Each suite's docstring says what its
layer promises; its test names say each promise; it proves them with nothing above that layer. When a
promise changes, its test changes first.

## What each suite proves

| Suite | Layer | Proves |
|---|---|---|
| `test_layers.py` | all | every module names its layer; imports point only down; layers 0 to 5 use only the standard library |
| `test_execution.py` | 0 | a `Spec` can't be built wrong or changed; an `Outcome` is exactly one of five |
| `test_process.py` | 1 | a process streams exactly what it writes, takes input, stops gracefully, is killed when it won't, leaves nothing running; a child inherits only the allowlist |
| `test_local.py` | 1 | on this machine, the loopback gateway holds the key and the run a token; file mode; nothing left after |
| `test_door.py` | 1 | the door tunnels only its hosts; the gateway forwards only the session's token, with the key in the shape's header; the key arrives on stdin only |
| `test_docker.py` | 1 | against a fake docker: every run hardened, behind its own door, its environment by name, at most a token, stopped by SIGINT, nothing left on any path; a sweep removes only its owner's |
| `test_docker_live.py` | 1 | the same, inside real containers: a stop reaches the process group, no DNS, only the given hosts, the key only in the door. `-m docker` |
| `test_workspace.py` | 2 | every change tracked; any file as any snapshot left it; no path out; internal paths hidden; history out of reach |
| `test_folder.py` | 3 | a folder loads only as contract 1 says, with every problem named at once |
| `test_install.py` | 3 | one install per version, keyed by exactly its inputs; nothing left by a failure; never twice at once; hardened under Docker with no secret |
| `test_contract.py` | 3 | exactly the environment and line 1; `home/` every response, `workspace/` once, `files` rendered or deleted; the harness's own status, every key it wrote, its changes and its reported artifacts |
| `test_response.py` | 3 | streaming, steers delivered or refused, a graceful stop, a kill, a timeout, a resumable stop, no key under the gateway, nothing left after a cancel |
| `test_hi_adapter.py` | — | the shared plumbing: a whole result file, line 1, steers, JSON-RPC, a stop told from a failure |
| `test_harness_live.py` | 3 | the base image, an install through a door that reaches only its hosts, and a response steered, stopped and resumed in real containers. `-m docker` |
| `test_store.py` | 4 | whole writes, private files, providers that never show their key, folders stored only when they load and installed in the background |
| `test_sessions.py` | 5 | sessions in the background, continuing, one response at a time, following, interrupt's degrade, stop, re-sent steers, artifacts, recovery, no key anywhere |
| `test_api.py` | 6 | every route and error; the Responses shape and SSE; interrupt and stop; responses outliving clients; the OpenAI SDK unchanged; no key served |
| `test_api_live.py` | 6 | the server, installing and running a folder sandboxed: streamed, steered, stopped, continued. `-m docker` |
| `test_live_script.py` | — | the live suite's secret audit blames only its own runs |

## The stand-ins

Tests need no Docker, keys or network:
- **The template folder's stand-in** (`harnesses/template`, through `tests/standin.py`): a small CLI
  that counts, takes steers, stops gracefully, resumes, reads its config from `home/` and reports usage.
  Every test from layer 3 up runs it, on this machine.
- **`tests/fakes/docker`** stands in for the Docker CLI: it records every call and runs a container's
  command as a plain process. Files in its state directory turn on failures and leftovers. The
  `fake_docker` fixture in `conftest.py` puts it on `PATH`.
- **`tests/upstream.py`** stands in for a provider: a TLS server that records each request and streams
  an answer, or breaks mid-stream.

## Writing a test

- **Put it in the lowest layer that can prove it.**
- **Name the promise, not the function:** `test_a_stop_after_the_end_changes_nothing`.
- **Test the negative space.** What must never happen is a promise too: a key in a log, a container
  left after a cancel, an internal path in a listing, a second response in a busy session.
- **Wait on events, not time.** Wait for a file, a line or a status, with a deadline; never a fixed sleep.

## The live suite

Only a real CLI on a real provider shows that a folder works. `scripts/live.py` runs one folder,
sandboxed, from the library and from the API (the server as a subprocess), under the gateway and with a
key file, and checks:

| Check | Passes when |
|---|---|
| install | a fresh data directory installs it; a second install is a cache hit |
| one-shot | the instructions reach the CLI, and it answers |
| usage | `usage` has the fixed keys, with tokens counted |
| config | every `hi-live-…` skill, MCP server and hook in `home/` is loaded |
| resume | a continued session recalls the first response |
| reported | the folder's `report` globs bring files back |
| steer | an interrupt is steered into a counting task, which stops early and does what the steer said |
| stop | a stop is graceful, and a continue recalls what it was doing |
| secrets | the key is in no log, record, workspace, environment or response |

```bash
uv run --extra dev python scripts/live.py harnesses/claude-code \
  --url https://api.anthropic.com --api anthropic-messages --key-file ~/anthropic.key
```

Run it for every folder a change can affect, and before every release. The steer and stop checks need a
model that runs one command per step; a model that writes all thirty numbers in one command can't be
steered mid-way, and fails `steer` for that reason alone. Note in the pull request what you ran and
what passed.
