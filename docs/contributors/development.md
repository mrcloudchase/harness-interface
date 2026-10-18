# Development

## Set up

You need git and [uv](https://docs.astral.sh/uv/). uv brings Python and every dependency. Docker
is needed only for the Docker tests and for running harnesses sandboxed.

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
uv run --extra dev pytest                      # the whole suite: no Docker, no keys, under a minute
```

The first `uv run` creates `.venv` with the package installed from the source, so every change is
live on the next run.

| Extra | Brings | For |
|---|---|---|
| none | `httpx`, for `hi` | the library and `hi` |
| `server` | FastAPI, uvicorn, pydantic | the server |
| `dev` | `server`, pytest, the OpenAI SDK | the tests |

## Run it from the source

```bash
uv run --extra server harness-interface                     # the server, in the foreground, on Docker
HI_RUNTIME=local uv run --extra server harness-interface    # harnesses as plain processes here
HI_DATA_DIR=/tmp/hi-dev uv run --extra server harness-interface   # with a throwaway data directory
uv run hi …                                                 # the CLI, against whichever server HI_URL names
```

Use a throwaway `HI_DATA_DIR` while you work, so your own providers and records stay untouched.
What the server keeps there:

| Path | |
|---|---|
| `providers/`, `sandboxes/`, `harnesses/` | the resources, one JSON file each |
| `scripts/{name}/` | each harness's scripts, mounted read-only into its runs |
| `records/{id}.json` | one per turn |
| `logs/{id}.out`, `logs/{id}.log` | a turn's stdout and stderr, byte for byte |
| `logs/build-*.log` | the output of each sandbox image build |
| `workspaces/{id}/` | each conversation's workspace, named after its first turn |

To run one harness folder with no server at all, use the library example:

```bash
uv run python examples/library/run_a_harness.py harnesses/codex "Say hi" \
    --provider-url https://api.openai.com/v1 --key-env OPENAI_API_KEY --workspace /tmp/ws
```

## Tests

```bash
uv run --extra dev pytest                      # everything that needs no Docker and no keys
uv run --extra dev pytest tests/test_harness.py -k cancel    # one file, some tests
uv run --extra dev pytest -m docker            # against a real Docker daemon
```

CI runs the whole suite on every pull request, on Python 3.11 (the oldest supported), 3.13 (the
installer's) and 3.14, and the Docker tests beside it. [Testing](testing.md) says what each suite proves, and how to write a test.

## Lint

```bash
uvx ruff check --select F,E9 --target-version py311 .
```

That is CI's check: unused imports and variables, undefined names, syntax errors. There is no
formatter; match the code around you ([conventions](conventions.md)).

## Working behind a TLS-intercepting proxy

On a network that intercepts TLS (a corporate proxy, some cloud development boxes), the CLIs inside
a sandbox reject the proxy's certificate. Build your own sandbox that trusts it, and point your
harnesses at it:

```dockerfile
FROM harness-interface/default:<tag>           # see `docker images 'harness-interface/*'`
USER root
RUN printf '%s\n' '-----BEGIN CERTIFICATE-----' 'MIID…' '…' '-----END CERTIFICATE-----' \
      > /usr/local/share/ca-certificates/proxy.crt && update-ca-certificates
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
USER 1000
```

A sandbox is built with an empty context, so `COPY` has nothing to copy: the certificate goes in
the Dockerfile itself, one quoted line of it per `printf` argument. Add it with `hi sandbox add`, and set `"sandbox"` in each harness you run.
It is for your machine only; never commit it.

## Debugging a run

- **What the harness printed:** `hi output ID` and `hi log ID`, or `logs/{id}.out` and `.log`.
- **What it was given:** `.hi/request.json` in its workspace, and the `HI_*` variables the
  [contract](../users/harness-contract.md) lists.
- **What it reported:** `.hi/output.json` in its workspace.
- **Why it never started:** the record's `error`; for an image build, `logs/build-*.log`.
- **What it did to the workspace:** `git -C WORKSPACE log -p`. Every turn is two commits,
  `prepare` and `turn`.
- **The container:** while a run is live, `docker ps --filter name=harness-` shows its
  container and door.
