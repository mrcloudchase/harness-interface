# Install, upgrade and uninstall

## Requirements

| | |
|---|---|
| **OS** | Linux or macOS |
| **git** | required: every session's workspace is tracked with git |
| **Docker** | required for sandboxed sessions, the default. On macOS: Docker Desktop, OrbStack or Colima. |
| **Disk** | about 400 MB for the base image, plus each harness's tools (150–400 MB each) |
| **curl** | for the installer |

You don't need Python: the installer brings [uv](https://docs.astral.sh/uv/), and uv brings Python.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
```

It checks for git, installs uv if it is missing, installs the latest release with `uv tool install`,
and says whether Docker is running. It installs one command, `harness-interface`: the server. If it
isn't found afterwards, open a new terminal.

`HI_REF` installs another version: a release tag (`v2.0.0`), a branch or a commit.

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | HI_REF=v2.0.0 sh
```

### Only the library

```bash
uv add "harness-interface @ git+https://github.com/mrcloudchase/harness-interface@v2.0.0"
```

The library needs only Python's standard library; the `[server]` extra adds FastAPI and uvicorn.

## Run the server

```bash
harness-interface
```

It listens on `http://127.0.0.1:8000` until you stop it (Ctrl-C), logging to the terminal. At startup it
checks for git, closes anything a restart cut off, and removes the containers and networks a crash left.
Settings are environment variables ([configuration](configuration.md)). To keep it running in the
background, use your system's service manager, or `nohup harness-interface > server.log 2>&1 &`.

To develop a harness folder without Docker, start it with `HI_RUNTIME=local`: harnesses then run as
plain processes on this machine, with no sandbox.

## Upgrade

Run the installer again. Your data stays. A new release's base image or a changed `install.sh` installs
the affected harnesses once more, on first use.

## Uninstall

```bash
uv tool uninstall harness-interface
rm -rf ~/.harness-interface               # providers, harnesses, sessions and workspaces
docker images 'hi-*'                      # the base and harness images; remove with docker rmi
```

## From source

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
uv run --extra server harness-interface
```

To work on harness-interface itself, see [docs/contributors](../contributors/README.md).
