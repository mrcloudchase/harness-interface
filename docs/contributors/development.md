# Development

## Set up

You need git and [uv](https://docs.astral.sh/uv/); uv brings Python and every dependency. Docker is
needed only for the Docker tests, the live suite, and running harnesses sandboxed.

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
uv run --extra dev pytest                      # the whole suite: no Docker, no keys, no network
```

The first `uv run` creates `.venv` with the package installed from the source, so every change is live
on the next run.

| Extra | Brings | For |
|---|---|---|
| none | nothing: the standard library | the library |
| `server` | FastAPI, uvicorn, pydantic | the server |
| `dev` | `server`, pytest, the OpenAI SDK, httpx | the tests and the live suite |

## Run it from the source

```bash
uv run --extra server harness-interface                            # the server, on Docker
HI_DATA_DIR=/tmp/hi-dev uv run --extra server harness-interface    # with a throwaway data directory
HI_RUNTIME=local uv run --extra server harness-interface           # harnesses as plain processes here
```

Use a throwaway `HI_DATA_DIR` while you work, so your own providers and sessions stay untouched. What it
holds is in [configuration](../users/configuration.md#where-data-lives).

## Test and lint

```bash
uv run --extra dev pytest                                   # everything but Docker
uv run --extra dev pytest tests/test_sessions.py -k steer   # one suite, some tests
uv run --extra dev pytest -m docker                         # against a real Docker daemon
uvx ruff check --select F,E9 --target-version py311 .       # CI's lint: unused code and syntax
```

Behind a proxy that re-signs TLS, give the Docker tests its CA bundle with `HI_CA_FILE`. CI runs the
suite on Python 3.11, 3.13 and 3.14, the Docker tests, and the lint, on every pull request.

## Develop a harness folder

Run it on this machine first, then sandboxed, with the [live suite](testing.md#the-live-suite):

```bash
uv run --extra dev python scripts/live.py harnesses/my-cli --local \
  --url https://api.anthropic.com --api anthropic-messages --key-file ~/anthropic.key
uv run --extra dev python scripts/live.py harnesses/my-cli \
  --url https://api.anthropic.com --api anthropic-messages --key-file ~/anthropic.key
```

`--local` needs the CLI's install to work on this machine; the sandboxed run is the one that counts.
Behind a proxy that re-signs TLS, pass `--ca-file` (or set `HI_CA_FILE`).

## Debug a response

| Look at | For |
|---|---|
| `harness.stderr` on the response, or `logs/{id}.stderr` | what `run.sh`, the adapter and the CLI said |
| `logs/{id}.stdout` | the CLI's own events, byte for byte |
| `logs/{id}.door` | each host the run asked for, and whether the door let it through |
| `runs/{id}/output.json` | the adapter's result file, as written |
| `workspaces/{session}/.home/` | the CLI's `$HOME`: its config as copied in, and its own state |
| `tools/{name}-{key}.log` | the install's output |
| `docker ps -a --filter label=hi.owner` | containers still running, by data directory |

To look inside the sandbox, run a folder whose `run.sh` prints what you want to see; it gets exactly
what a harness gets.
