# Install, upgrade and uninstall

## Requirements

| | |
|---|---|
| **OS** | Linux or macOS |
| **git** | required: every conversation's workspace is a git repository |
| **Docker** | required for sandboxed runs, the default. On macOS: Docker Desktop, OrbStack or Colima. |
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
4. reports whether Docker is running.

It installs two commands into `~/.local/bin`:

| Command | |
|---|---|
| `harness-interface` | the API server |
| `hi` | the command line, a client of the API ([reference](../reference/cli.md)) |

If `hi` isn't found, open a new terminal; uv adds `~/.local/bin` to your shell's `PATH`. To check
the install, run `hi --version`.

### A particular version

Set `HI_REF` to a tag, a branch or a commit:

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | HI_REF=<tag> sh
```

## Run the server

| | |
|---|---|
| `hi server start` | in the background, logging to `~/.harness-interface/server.log` |
| `harness-interface` | in the foreground, logging to the terminal |

Either way it listens on `http://127.0.0.1:8000`. At startup it checks for git and, with the
Docker runtime, a running Docker. It won't start without them, and says which one is missing.

To run harnesses without Docker, start it with `HI_RUNTIME=local`. See
[runtimes](../reference/configuration.md#runtimes) for what that gives up. Every setting is
listed in [configuration](../reference/configuration.md).

## Upgrade

Run the installer again. It replaces what is installed, and your data stays.

## Uninstall

```bash
hi server stop
uv tool uninstall harness-interface
rm -rf ~/.harness-interface                    # your providers, harnesses, records and workspaces
docker images 'harness-interface/*'            # the built sandbox images; remove with docker rmi
```

## From source

To work on harness-interface itself:

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
uv run harness-interface                       # the server, from the source
uv run hi …                                    # the CLI, from the source
uv run --extra dev pytest                      # the tests: no Docker or keys needed
```
