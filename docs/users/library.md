# The Python library

Everything the server does, it does through a library you can use directly: run a harness, or
anything else, in a sandbox, from Python, with no server and no HTTP. The library needs nothing
beyond Python's standard library and git.

```bash
uv add "harness-interface @ git+https://github.com/mrcloudchase/harness-interface@v1.0.0"
```

Use the library when your program is in Python and runs the harnesses itself, such as a loop, a
test rig or your own agent. Use [the server](api-clients.md) when you want records, conversations
others can follow, or a client in another language.

## Run a harness folder

A harness folder (a `harness.json` and its scripts) runs the same way here as through the server:

```python
import asyncio
import os
from pathlib import Path

from harness_interface import Docker, DockerRuntime, Harness, Provider, Request, Turn
from harness_interface.resources import DEFAULT_SANDBOX


async def main():
    folder = Path("harnesses/claude-code").resolve()
    harness = Harness.from_folder(folder)
    provider = Provider("anthropic", "https://api.anthropic.com", os.environ["ANTHROPIC_API_KEY"])
    runtime = DockerRuntime(Docker(Path("logs")), DEFAULT_SANDBOX, egress=[provider.host], mounts=[folder])

    turn = await Turn.start(runtime, harness, provider, Request("Write a haiku about a hermit crab."),
                            workspace=Path("work").resolve(), scripts=folder)
    async for event in turn.events():            # the harness's own output, as it prints it
        print(event.stream, event.data.decode(errors="replace"), end="")
    result = await turn.result()
    print(result.status, result.answer, result.session_id, result.files)


asyncio.run(main())
```

- **`Turn.start`** prepares the workspace, starts the run and returns at once. A request the
  harness contract can't carry out, such as an unknown template placeholder or a file path outside
  the workspace, raises `Invalid` here, before anything runs.
- **`turn.events()`** yields `Event(stream, data)`: bytes, on `stdout` and `stderr`, as the
  harness writes them.
- **`turn.result()`** is a `Result`:

  | Field | |
  |---|---|
  | `status` | `ok`, `fail`, `timeout` or `cancelled` |
  | `exit_code` | the exit code, or `None` if it never ran or was stopped |
  | `answer`, `session_id`, `usage`, `cost_usd` | what the harness reported |
  | `error` | why it never ran, if it didn't |
  | `files`, `deleted` | what this turn added or changed, and deleted |
  | `base`, `commit` | the workspace's snapshots before and after the turn |

- **`turn.cancel()`** stops it, from any thread, at any point. While the sandbox is still being set
  up, the harness never starts.

**To continue the conversation,** start another turn with the same workspace, and the session the
last one reported: `Request("Now give it a title.", session_id=result.session_id)`.

**To run without Docker,** use `LocalRuntime()` instead of `DockerRuntime(...)`. The harness then
runs as a plain process on your machine, with no isolation.

A complete, runnable version is [examples/library/run_a_harness.py](../../examples/library/run_a_harness.py).

## Run anything in a sandbox

Below the harness contract is the execution core, which runs any command:

```python
from harness_interface import Docker, DockerRuntime, LocalRuntime, Sandbox, Spec

box = Sandbox("py", "FROM python:3.12-slim\nRUN useradd -u 1000 runner\nUSER runner\n", egress=("pypi.org",))
runtime = DockerRuntime(Docker(Path("logs")), box)

execution = await runtime.start(Spec(["python3", "-c", "print('hi')"], timeout_s=60))
async for event in execution.events():
    ...
outcome = await execution.wait()                 # Outcome: exited(code), timed_out, cancelled or failed(reason)
```

| | |
|---|---|
| `Spec(command, input=b"", env={}, workspace=None, timeout_s=None, interactive=False)` | what to run. `input` is written first; with `interactive=True` the input stays open |
| `runtime.start(spec)` | starts it. A failure to start is an execution whose outcome is `failed`, not an exception |
| `execution.events()` | bytes on named streams, as they arrive; iterate once |
| `execution.send(data)`, `execution.end_input()` | more input, for an interactive spec |
| `execution.cancel()` | stop it, from any thread |
| `execution.wait()` | the `Outcome`, the same every time it is asked |

A `Spec` refuses what can't run: an empty command, input that isn't bytes, environment values
that aren't strings, a timeout that isn't positive. Each raises `Invalid`.

## Runtimes

| | Guarantees |
|---|---|
| `DockerRuntime(engine, sandbox, egress=[...], mounts=[...])` | a fresh container per run: no capabilities, a read-only root, a non-root user, process and memory limits, and no way out except tunnels to the allowed hosts. The workspace is mounted read-write and `mounts` read-only, each at its own path. One `Docker(build_logs)` engine builds each Dockerfile's image once; share it between runtimes |
| `LocalRuntime()` | none: a process on this machine, as you |

`runtime.recover()` removes whatever runs left behind when a program crashed: containers,
networks. The server calls it at startup; call it at your program's start if it uses
`DockerRuntime`.

## The public API

Everything below is importable from `harness_interface`:

| | |
|---|---|
| `Spec`, `Event`, `Outcome`, `Execution`, `Runtime` | the execution core |
| `LocalRuntime`, `DockerRuntime`, `Docker`, `Sandbox` | where things run |
| `Workspace` | a git-backed working directory: snapshots, changes, diffs, files at a snapshot |
| `Harness`, `Provider`, `Request`, `Result`, `Run`, `Turn` | the harness contract, and one turn of a harness |
| `Invalid`, `NotFound`, `Conflict` | refusals |

The layers above (`resources`, `routing`, `platform`) are importable too, for building your own
server or front end; see [docs/contributors](../contributors/architecture.md) for how they fit.
