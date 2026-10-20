# The Python library

The server is built on a library you can use directly: the same sessions, sandbox and harness folders,
in your own Python process, with no server and no HTTP. It needs only Python's standard library, git
and Docker.

```bash
uv add "harness-interface @ git+https://github.com/mrcloudchase/harness-interface@v2.0.0"
```

## Run a session

```python
import asyncio
from pathlib import Path

from harness_interface import Ask, Images, Placement, ProviderEntry, Sessions, owner_of
from harness_interface.store import folder_map


async def main():
    data = Path("hi-data").absolute()
    sessions = Sessions(data, Placement(Images(data / "logs"), owner=owner_of(data)))
    await sessions.recover()                       # sweep what a crash left, as the server does at start

    sessions.registry.put_provider(ProviderEntry("anthropic", "https://api.anthropic.com", "anthropic-messages",
                                                 Path("~/anthropic.key").expanduser().read_text().strip()))
    await sessions.registry.put_harness("claude-code", folder_map(Path("harnesses/claude-code")))
    await sessions.registry.ready("claude-code")   # waits for its install, once per version

    session = await sessions.start(Ask("claude-code", "Write hello.py that prints hello.",
                                       instructions="Keep it to one file."))
    rid = session.responses[-1]
    async for event in sessions.follow(rid):       # its own output, as it prints it
        if event.kind == "stdout":
            print(event.data.decode(errors="replace"), end="")
    record = await sessions.wait(rid)
    print(record.status, record.answer)
    print(sessions.artifacts(rid).changes)         # {"hello.py": b"print('hello')\n"}

    again = await sessions.start(Ask("claude-code", "Make it print goodbye too.", previous=rid))
    await sessions.wait(again.responses[-1])
    await sessions.close()


asyncio.run(main())
```

`Sessions` is everything the HTTP API does:

| | |
|---|---|
| `start(ask)` | a new session, or with `previous` a continued one; returns the session at once, its response running |
| `follow(id)` | every event of a session or response, as it comes: `created`, `stdout`, `stderr`, `steer`, `interrupted`, `completed` |
| `wait(response_id)` | the response record, once it has ended |
| `interrupt(session_id, text)` | `("steered" \| "continued" \| "responded", record)` |
| `stop(session_id, timeout_s=None)` | `"stopped"`, `"killed"` or `"idle"` |
| `artifacts(response_id)` | stdout, stderr, diff, changes, files, reported artifacts and the harness's output |
| `session(id)`, `sessions()`, `response(id)` | the records |
| `registry` | providers and harness folders, as the API's resources |
| `recover()`, `close()` | at start, at the end |

`Ask(model, task, instructions="", files={}, previous=None, metadata={})`: `model` is
`harness[@provider][/model]`, and `files` maps workspace paths to text or bytes.

`Placement(None)` runs harnesses as plain processes on this machine, with no sandbox, for developing a
folder.

## Below sessions

One response of a harness, on any runtime, is `harness_interface.Response`; the contract it follows is
`prepare` and `collect` in `harness_interface.harness.contract`. Below that, `Spec`, `Execution` and
`Runtime` run any command: `DockerRuntime` in a hardened container behind its egress door, or
`LocalRuntime` on this machine. They are the layers the rest is built on; see
[architecture](../contributors/architecture.md).
