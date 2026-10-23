<p align="center">
  <img src="docs/assets/picky.png" width="240" alt="Picky, the harness-interface mascot: a hermit crab with no shell of its own">
</p>

<h1 align="center">harness-interface</h1>

<p align="center">
  <b>A multi-tenant platform that runs coding-agent CLIs sandboxed behind the OpenAI Responses API.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/runs-sandboxed%20in%20Docker-2496ed" alt="Runs sandboxed in Docker">
  <img src="https://img.shields.io/badge/API-OpenAI%20Responses-412991" alt="OpenAI Responses API">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0"></a>
  <a href="https://github.com/mrcloudchase/harness-interface/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mrcloudchase/harness-interface/ci.yml?branch=main&label=CI" alt="CI"></a>
</p>

A tenant brings its **providers** (model endpoints and keys, sealed on arrival) and its **harness
packages** (how to install a CLI, how to run one turn, what to return). Members send
`POST /v1/responses` with `model` naming a harness. The platform runs the package in a fresh
sandbox it owns, relays the CLI's provider calls through a gateway that holds the keys, streams
the output back, and returns exactly what the package decided. Twenty-two packages ship in the
catalog, verified live.

```
                 OpenAI Responses API (any SDK, curl, the console)
                                  │
    api  ─── records (SQLite | Postgres) ─── blobs (directory | S3)
    gateway  holds the provider keys, relays provider calls, meters, captures
    worker   joins with a token, pulls turns, runs each in a fresh sandbox
                                  │
         sandbox: the package's CLI, a door as its only way out, a token instead of a key
```

## Run it

```bash
mkdir -p /srv/hi/data
docker run -d --name hi --restart unless-stopped -p 127.0.0.1:8000:8000 -p 127.0.0.1:8081:8081 \
  -v /var/run/docker.sock:/var/run/docker.sock -v /srv/hi/data:/srv/hi/data -e HI_DATA_DIR=/srv/hi/data \
  --add-host host.docker.internal:host-gateway ghcr.io/mrcloudchase/harness-interface:4.0.0
docker exec hi harness-interface init --tenant acme --owner chase     # prints the deployer key and your key, once
open http://127.0.0.1:8000                                            # the console; the docs are at /docs
```

Add a provider, fork a package from the catalog, and send a request:

```bash
curl -s http://127.0.0.1:8000/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Create hello.txt containing the word hello, then reply with the one word: done"}'
```

## Watch it

<p align="center">
  <img src="docs/assets/casts/claude-code.gif" width="800" alt="Claude Code takes a streamed turn and a steer through harness-interface">
</p>

Claude Code taking a streamed turn and a steer, recorded as it ran. The documentation's
[demos page](docs/demos.md) has six harnesses.

## Documentation

The documentation is served by the platform itself at `/docs`, and its source is in
[`docs/`](docs/): [deploy](docs/deploy.md), [initialize](docs/initialize.md),
[sign in](docs/sign-in.md), [providers](docs/providers.md), [harnesses](docs/harnesses.md),
[first request](docs/first-request.md), [sessions](docs/sessions.md),
[steer and cancel](docs/steer-and-cancel.md), [traces and captures](docs/traces-and-captures.md),
[members and keys](docs/members-and-keys.md), [clients](docs/clients.md),
[tenants and limits](docs/tenants.md), [workers and scale](docs/workers.md),
[configuration](docs/configuration.md), [security](docs/security.md),
[troubleshooting](docs/troubleshooting.md), [write a package](docs/packages.md),
[the catalog](docs/catalog/index.md), [demos](docs/demos.md), [API](docs/api.md),
[architecture](docs/architecture.md), [contributing](docs/contributing.md).

## The same code, hosted or self-hosted

One image, four roles (`api`, `gateway`, `worker`, `all`), one compose file with a one-box
profile and a fleet profile. Records in SQLite or Postgres, blobs in a directory or any S3-API
store, and no cloud SDK anywhere else. `HI_SIGNUP=open` turns the sign-in page into a sign-up
page; closed, the deployer creates tenants and sets their ceilings.

## License

Apache 2.0.
