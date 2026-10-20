# Configuration

Everything is set through environment variables, read when the server starts; there is no
configuration file.

| Variable | Default | |
|---|---|---|
| `HI_HOST` | `127.0.0.1` | the address to listen on |
| `HI_PORT` | `8000` | the port |
| `HI_DATA_DIR` | `~/.harness-interface/data` | where everything is kept |
| `HI_RUNTIME` | `docker` | `docker`: every install and response in a hardened container. `local`: plain processes on this machine, no isolation, for developing a harness |
| `HI_CA_FILE` | none | a CA bundle, for a network that re-signs TLS (a corporate proxy); given to the egress door and to harnesses in file mode |

The installer reads `HI_REF`: the release tag, branch or commit to install.

The server passes nothing of its own environment to what it runs but an allowlist (`PATH`, locale,
terminal and time zone, proxy and CA settings, and Docker's client settings), so a key in the server's
environment never reaches a harness.

## Where data lives

Under `HI_DATA_DIR`:

```
providers/{name}.json       providers and their keys: files mode 600, in a mode 700 directory
harnesses/{name}/           each harness folder, as it was sent
tools/{name}-{key}/         each harness's install, by version (a hash of install.sh, image.Dockerfile,
                            the base image and the CPU); {name}-{key}.log is its install log
sessions/{id}.json          each session, private
responses/{id}.json         each response's record
logs/{id}.stdout, .stderr   each response's output, byte for byte; .door, its egress door's log;
                            image build logs
runs/{id}/output.json       each response's result file, outside its workspace
workspaces/{session}/       each session's workspace; .home/ inside it is the harness's $HOME
```

## Images and containers

The base image is `hi-base:<hash of its Dockerfile>`; a harness with an `image.Dockerfile` gets
`hi-harness-<name>:<hash>`. A response's containers and network are named `hi-run-…`, `hi-door-…` and
`hi-net-…`, and carry a label with their data directory's id, so a server only ever removes its own.
