# Deploying

One image, one compose file, four roles. The same artifact is the hosted platform and the self-hosted
one; the difference is `HI_SIGNUP` and how many machines you point it at.

## The roles

| Role | What it does | Holds | Scales |
|---|---|---|---|
| `api` | the Responses API, the tenant and deployer routes, the console, the workers' routes | the master key | any number behind a load balancer |
| `gateway` | relays sandboxes' provider calls, swaps the session token for the key, meters, captures | the master key | any number behind a load balancer |
| `worker` | joins with a token, pulls turns, runs them in sandboxes on its Docker host, pushes snapshots | a worker credential and a cache; no keys, no database, no bucket credentials | one per machine, any number of machines |
| `all` | the three above in one process | | one box |

`harness-interface serve --role api,gateway` and `--role worker` run roles apart; `--role all` is
the default.

## One box

```bash
mkdir -p /srv/hi/data && cd deploy && docker compose --profile one-box up -d
docker compose exec platform harness-interface init --tenant acme --owner chase
```

Every role in one container over SQLite and a blob directory on `/srv/hi/data`, Caddy in front
with a certificate for `HI_DOMAIN` (self-signed for `localhost`). The container mounts the Docker
socket to run sandboxes and the data directory at the same path as on the host. Back up the data
directory; it holds everything.

Without compose: `uv tool install` the package, `harness-interface init`, `harness-interface serve`,
with Docker on the box and a reverse proxy of your choice in front.

## Many boxes

```bash
docker compose --profile ha up -d
```

The same compose file: two `api,gateway` containers behind Caddy, a `worker`, Postgres and MinIO.
Point `HI_RECORDS` at any Postgres and `HI_BLOBS` at any S3-API store (R2, B2, S3, MinIO, Garage)
to use managed ones; the two in the file are a start. Add a machine by running the worker role on it:

```bash
docker run -d --restart unless-stopped -v /var/run/docker.sock:/var/run/docker.sock -v /srv/hi/data:/srv/hi/data \
  --add-host host.docker.internal:host-gateway \
  -e HI_DATA_DIR=/srv/hi/data -e HI_CONTROL_URL=https://hi.example.com -e HI_JOIN_TOKEN=… \
  -e HI_GATEWAY_URL=https://gateway.hi.example.com -e HI_RUNTIME=runsc \
  ghcr.io/mrcloudchase/harness-interface:4.0.0 serve --role worker
```

`deploy/worker.cloud-init.yml` is the same as a cloud-init file for an autoscaling group. A worker
that stops heartbeating for 45 seconds loses its turns in flight, which are recorded as failed; its
sessions continue on another worker from their last snapshot. Removing a worker is stopping it.

## What each piece needs

- **The data directory.** Workers keep caches there (packages, tools layers, session trees between
  turns) and bind-mount session trees into sandboxes by their host paths, so a containerized worker
  mounts it at the same path inside and out. On one box it also holds the master key, SQLite and the
  blobs.
- **The gateway's address.** Each sandbox's door forwards provider calls to `HI_GATEWAY_URL`. On one
  box that is `http://host.docker.internal:8081`, the gateway on the host. Across machines it is a TLS
  address behind your load balancer, reachable from every worker host.
- **The master key.** `HI_MASTER_KEY` (64 hex digits) in the environment of `api` and `gateway`,
  from your secrets manager; or the file `init` wrote on one box.
- **The join token.** `HI_JOIN_TOKEN` on the control plane and on every worker. The `all` role
  generates one for its in-process worker.
- **The base image.** `HI_BASE_IMAGE` names the sandbox image every turn runs in. Empty, each worker
  builds the shipped one (`harness_interface/runtimes/base.Dockerfile`: Debian, Python 3.12, Node 22,
  git, curl, ripgrep). For a fleet, build it once in CI (`.github/workflows/base-image.yml` builds,
  scans and publishes it) and set the variable to the published reference.
- **A sandboxed runtime.** Install gVisor on worker machines and set `HI_RUNTIME=runsc`; every
  sandbox then runs under it. Strongly recommended wherever tenants are not one trusting team.
- **Caddy or any load balancer** for TLS in front of `api`; the health route is `/healthz`.

## Upgrading

Replace the image tag and restart. `api` and `gateway` are stateless; restart a worker when it is
idle, or let its turns fail over. The records table and the blob layout are versioned by the
changelog, and a newer server reads an older data directory.

## Nothing cloud-named

The package imports a database driver and an S3 client and nothing else of any cloud, and the test
suite fails if that changes. Terraform or cloud-specific templates, if you keep any, live beside the
repository, not in it.
