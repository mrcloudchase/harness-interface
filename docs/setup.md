# Setup

Install harness-interface, start the server, configure it, and fix the common problems.

## Requirements

| | |
|---|---|
| **OS** | Linux or macOS |
| **git** | required; every conversation's workspace is a git repository |
| **Docker** | required for sandboxed runs, which are the default. On macOS that means Docker Desktop, OrbStack or Colima. |
| **Disk** | about 10 GB for the default sandbox image, built once |
| **curl** | for the installer |

You don't need Python. The installer brings [uv](https://docs.astral.sh/uv/), and uv brings
Python 3.12.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
```

The installer:
1. checks for git, and stops with how to install it if git is missing;
2. installs uv, if it isn't installed already;
3. installs the package from GitHub with `uv tool install`, in an environment of its own;
4. tells you whether Docker is running.

You end up with two commands on your `PATH`:

| Command | What it is |
|---|---|
| `harness-interface` | the API server |
| `hi` | the command line, a client of that API ([cli.md](cli.md)) |

To install a particular version, set `HI_REF` to a tag, a branch or a commit:

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | HI_REF=<tag> sh
```

If `hi` isn't found afterwards, open a new terminal. uv puts both commands in `~/.local/bin`,
and adds that directory to your shell's `PATH`.

## Start the server

```bash
hi server start      # in the background
hi server status
hi server logs
hi server stop
```

To keep it in the foreground instead, run `harness-interface`. Either way it listens on
`http://127.0.0.1:8000`. It starts with:
- no providers and no harnesses;
- one built-in sandbox, `default`.

At startup the server checks for git, and with the Docker runtime, for a running Docker. It
won't start without them, and says which one is missing.

## Configure

The server reads its settings from the environment:

| Variable | Default | |
|---|---|---|
| `HI_HOST` | `127.0.0.1` | the address to listen on |
| `HI_PORT` | `8000` | the port |
| `HI_DATA_DIR` | `~/.harness-interface/data` | resources, records, logs and workspaces |
| `HI_RUNTIME` | `docker` | where harnesses run: `docker` or `local` |

`hi` reads one variable of its own:

| Variable | Default | |
|---|---|---|
| `HI_URL` | `http://127.0.0.1:8000` | the server it talks to; `hi server start` starts the server on this address |

Keep the server on localhost. It has no authentication, and provider keys pass through it.

## Choose a runtime

| Runtime | Where a harness runs | What it needs |
|---|---|---|
| `docker` (default) | a fresh container from its sandbox's image, locked down, with one way out: its provider | Docker |
| `local` | a plain process on this machine, in the conversation's workspace | the harness's own CLI installed on this machine |

`local` has no isolation and no egress rule. Use it to develop a harness, or where Docker isn't
an option. Start it with `HI_RUNTIME=local hi server start`. Every record says which runtime it
ran on.

## Add providers and harnesses

```bash
hi provider add anthropic --url https://api.anthropic.com --key-env ANTHROPIC_API_KEY
hi harness add --builtin              # all 23 shipped harnesses; or name the ones you want
```

Each shipped harness names a provider, such as `anthropic`, `openai` or `deepseek`. Add
providers under those names, or change `provider` in a harness's `harness.json`. The names and
urls are listed in [harnesses/README.md](../harnesses/README.md).

## The first run

The first request that uses a sandbox builds that sandbox's image. For `default` the build
takes several minutes. Until it finishes, `hi run` shows nothing. After that, every run starts
from the built image in seconds. Changing a sandbox's Dockerfile builds a new image on the next
run that uses it.

## Upgrade and uninstall

To upgrade, run the installer again; it replaces what is installed. To uninstall:

```bash
hi server stop
uv tool uninstall harness-interface
rm -rf ~/.harness-interface              # your data: providers, harnesses, records, workspaces
docker images 'harness-interface/*'      # the built sandbox images, to remove with docker rmi
```

## From source

To work on harness-interface itself:

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
uv run harness-interface                 # the server, from the source
uv run hi …                              # the CLI, from the source
uv run --extra dev pytest                # the tests; they need no Docker and no keys
```

## Troubleshooting

| You see | What it means |
|---|---|
| `install: git is required` | Install git (`apt install git`, `brew install git`, or `xcode-select --install`), then run the installer again. |
| `Docker is not installed` / `Docker is not reachable` from `hi server start` | Start Docker, or use `HI_RUNTIME=local`. |
| `hi: no server at http://127.0.0.1:8000` | Run `hi server start`. If the server runs elsewhere, set `HI_URL`. |
| `hi run` shows nothing for minutes | The sandbox image is building. `hi server logs` shows the server; the build log is in `~/.harness-interface/data/logs/`. |
| a run `failed` with exit 127 on the local runtime | The harness's CLI isn't installed on this machine. `hi log <id>` shows the error. |
| any other failed run | `hi log <id>` shows the harness's stderr, and `hi output <id>` its stdout. |
| a port is already in use | Set `HI_PORT` for the server and `HI_URL` for `hi`. |
