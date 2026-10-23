# Deploy

One image, four roles, two shapes. Pick one box to start; the fleet shape uses the same image
and the same variables.

## What you need

- A Linux machine with Docker. Every turn runs in a container the platform starts through the
  Docker socket.
- A data directory mounted at the **same path inside and outside** the platform's container.
  Workers bind-mount session trees into sandboxes by their host paths, so the path must agree.
- A name and TLS in front, for anything beyond your laptop. The compose file brings Caddy.

## One box with Docker

```bash
mkdir -p /srv/hg/data
docker run -d --name hg --restart unless-stopped \
  -p 127.0.0.1:8000:8000 -p 127.0.0.1:8081:8081 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /srv/hg/data:/srv/hg/data -e HG_DATA_DIR=/srv/hg/data \
  --add-host host.docker.internal:host-gateway \
  ghcr.io/mrcloudchase/harnessgateway:5.0.0
```

That runs `serve --role all`: the API on 8000, the gateway on 8081, and a worker that builds the
sandbox base image on first start (a few minutes) and then takes turns. The home page is at
`http://127.0.0.1:8000/`, the app at `/app`, this documentation at `/docs/`, the OpenAPI reference
at `/reference`.

On a Mac with Docker Desktop, replace `/srv/hg/data` with a directory under your home, such as
`$HOME/hg`, on both sides of the `-v` and in `HG_DATA_DIR`.

## One box with compose and TLS

```bash
git clone https://github.com/mrcloudchase/harnessgateway && cd harnessgateway/deploy
mkdir -p /srv/hg/data
HG_DOMAIN=hg.example.com docker compose --profile one-box up -d
```

Every role in one container over SQLite and a blob directory on `/srv/hg/data`, with Caddy
terminating TLS for `HG_DOMAIN` (a certificate from Let's Encrypt, or self-signed for
`localhost`). Set `HG_SIGNUP=open` in the environment to let anyone create a tenant from the
app; leave it closed to create tenants yourself.

## The roles

| Role | Does | Holds | Scales |
|---|---|---|---|
| `api` | the Responses API, the tenant and deployer routes, the web surface, the workers' routes | the master key | any number behind a load balancer |
| `gateway` | relays sandboxes' provider calls, swaps the session token for the key, meters, captures | the master key | any number behind a load balancer |
| `worker` | joins with a token, pulls turns, runs them in sandboxes on its Docker host, pushes snapshots | a worker credential and a cache | one per machine, any number of machines |
| `all` | the three in one process | | one box |

`harnessgateway serve --role api,gateway` and `--role worker` run roles apart.

## A fleet

```bash
docker compose --profile ha up -d
```

The same file: two `api,gateway` containers behind Caddy, a worker, Postgres and MinIO. Point
`HG_RECORDS` at any Postgres and `HG_BLOBS` at any S3-API store (S3, R2, B2, MinIO, Garage) to
use managed ones. Give `api` and `gateway` the master key from your secrets manager as
`HG_MASTER_KEY`, and set `HG_JOIN_TOKEN` on the control plane and on every worker.

Add a machine by running the worker role on it, with the gateway's address as that machine's
sandboxes will reach it:

```bash
docker run -d --name hg-worker --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock -v /srv/hg/data:/srv/hg/data \
  --add-host host.docker.internal:host-gateway \
  -e HG_DATA_DIR=/srv/hg/data -e HG_CONTROL_URL=https://hg.example.com -e HG_JOIN_TOKEN=… \
  -e HG_GATEWAY_URL=https://gateway.hg.example.com -e HG_RUNTIME=runsc \
  ghcr.io/mrcloudchase/harnessgateway:5.0.0 serve --role worker
```

`deploy/worker.cloud-init.yml` is the same as a cloud-init file for an autoscaling group:
Docker, gVisor, the worker. [Workers and scale](workers.md) covers capacity and failure.

## Without Docker for the platform itself

Docker is still needed for the sandboxes, but the platform can run as a plain process:

```bash
uv tool install harnessgateway          # or: pip install harnessgateway
harnessgateway init --tenant acme --owner chase
harnessgateway serve
```

The data directory defaults to `~/.harnessgateway`. Put a reverse proxy in front for TLS.

## Upgrading

Replace the image tag and restart. `api` and `gateway` are stateless. Restart a worker when it is
idle, or let its turns fail over: a worker that stops heartbeating for forty-five seconds loses
its turns in flight, which are recorded as failed, and its sessions continue elsewhere from their
last snapshot. Back up the data directory on one box; it holds everything.

Next: [Initialize](initialize.md).
