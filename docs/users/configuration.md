# Configuration

Everything is set through environment variables; there is no configuration file.

## The server

Read when `harness-interface` (or `hi server start`) starts:

| Variable | Default | |
|---|---|---|
| `HI_HOST` | `127.0.0.1` | the address to listen on |
| `HI_PORT` | `8000` | the port |
| `HI_DATA_DIR` | `~/.harness-interface/data` | where resources, records, logs and workspaces live |
| `HI_RUNTIME` | `docker` | where harnesses run: `docker` or `local` ([below](#runtimes)) |

At startup the server checks that git is installed. With the Docker runtime, it also checks that
Docker is reachable. If either check fails, it refuses to start and says which one.

## The CLI

| Variable | Default | |
|---|---|---|
| `HI_URL` | `http://127.0.0.1:8000` | the server `hi` talks to; `--url` overrides it for one command |

`hi server start` starts the server on the host and port in `HI_URL`, and passes the rest of your
environment through: `HI_RUNTIME=local hi server start` starts a local-runtime server.

## The installer

| Variable | Default | |
|---|---|---|
| `HI_REF` | the latest release | the tag, branch or commit to install |

## Runtimes

| | `docker` (default) | `local` |
|---|---|---|
| A harness runs as | a fresh container from its sandbox's image | a plain process, in the workspace directory |
| It needs | Docker | the harness's CLI installed on this machine |
| Isolation | every capability dropped, read-only root, process and memory limits ([security](security.md)) | none |
| Network | only its provider's host, plus its sandbox's `egress` | anything this machine can reach |
| A sandbox's Dockerfile | is built and used | is ignored |
| Use it for | everything | developing a harness, or where Docker isn't an option |

Every record says which runtime it ran on, in `harness.runtime`.

## Where data lives

Under `HI_DATA_DIR`:

```
providers/{name}.json      the keys: files mode 600, in a mode 700 directory
sandboxes/{name}.json      the sandboxes you added; default is built in, not stored
harnesses/{name}.json
scripts/{harness}/         each harness's scripts, mounted read-only into its runs
records/{id}.json          the records, one per turn
logs/{id}.out              each run's stdout, byte for byte
logs/{id}.log              each run's stderr
logs/build-{sandbox}-{hash}.log
workspaces/{id}/           one per conversation, named after its first response; a git repository
```

`hi` keeps three files of its own in `~/.harness-interface`:

| | |
|---|---|
| `server.pid` | the server `hi server start` started |
| `server.log` | that server's log |
| `last-response` | the response `hi run -c` continues |

Docker images are named `harness-interface/{sandbox}:{hash of the Dockerfile}`. A run's
containers and network share a random id of their own: `harness-run-…`, `harness-door-…` and
`harness-net-…`.
