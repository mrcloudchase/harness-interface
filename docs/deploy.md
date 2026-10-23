# Deploy

One image, four roles, two shapes. One box is one command; the fleet shape uses the same image
and the same variables.

## What you need

Docker. A Linux server, or Docker Desktop on a Mac; the image is built for amd64 and arm64.
Every turn runs in a container the platform starts through the Docker socket, so the socket is
mounted. Nothing else: no cloud account, no directory to prepare, no second port.

## One box

```bash
docker run -d --name hg -p 127.0.0.1:8000:8000 \
  -v /var/run/docker.sock:/var/run/docker.sock -v hg:/data ghcr.io/mrcloudchase/harnessgatewayai
```

That runs `serve --role all`: the API on 8000, the gateway, and a worker that pulls the sandbox
base image and then takes turns. The first boot makes the deployer key, a tenant and its owner's
key, and prints them once: `docker logs hg`. The home page is at
`http://127.0.0.1:8000/`, the app at `/app`, this documentation at `/docs/`, the OpenAPI reference
at `/reference`. Add `--restart unless-stopped` on a server.

Everything the platform keeps is on the `hg` volume at `/data`: the master key, the records, the
blobs, the worker's caches. The sandboxes are started by the host's daemon, so what they mount
has to be a path the daemon knows. The platform does not ask you for one: at start it inspects
its own container, learns where the daemon keeps the volume, and translates every mount it makes.
The scripts it runs inside a sandbox and each turn's token are copied under `/data/worker` first,
so nothing of the platform container's own filesystem is ever shared. The same applies to the
gateway: a sandbox's door reaches it at the platform container's own address on its own network.
No port is published for it and nothing is bound to the host. This is why the same command works
on a Mac, where the volume lives inside Docker Desktop's VM and the daemon's paths are not yours.

## One box with compose and TLS

```bash
git clone https://github.com/mrcloudchase/harnessgatewayai && cd harnessgatewayai/deploy
HG_DOMAIN=hg.example.com docker compose --profile one-box up -d
```

Every role in one container over SQLite and a blob directory on the `hg-data` volume, with Caddy
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
`HG_MASTER_KEY`, and set `HG_JOIN_TOKEN` on the control plane and on every worker. The worker in
the file reaches the gateway at `http://api:8081` over the compose network; its sandboxes' doors
are put on that same network.

Add a machine by running the worker role on it, with the gateway's address as that machine's
sandboxes will reach it:

```bash
docker run -d --name hg-worker --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock -v hg:/data \
  -e HG_CONTROL_URL=https://hg.example.com -e HG_JOIN_TOKEN=… \
  -e HG_GATEWAY_URL=https://gateway.hg.example.com -e HG_RUNTIME=runsc \
  ghcr.io/mrcloudchase/harnessgatewayai serve --role worker
```

`HG_GATEWAY_URL` is the one thing a worker on another machine must be told: the gateway, as a
sandbox on that machine reaches it, which is a TLS address behind your load balancer.
`deploy/worker.cloud-init.yml` is the same as a cloud-init file for an autoscaling group:
Docker, gVisor, the worker. [Workers and scale](workers.md) covers capacity and failure.

## Without Docker for the platform itself

Docker is still needed for the sandboxes, but the platform can run as a plain process:

```bash
uv tool install harnessgateway          # or: pip install harnessgateway
harnessgateway serve                    # the first boot prints the keys
```

The data directory defaults to `~/.harnessgateway`. A process on the host shares the daemon's
view of paths, so nothing is translated; its sandboxes reach the gateway through
`host.docker.internal`, or through `HG_GATEWAY_URL` when that is not where the gateway is. Put a
reverse proxy in front for TLS.

## Upgrading

Pull the new image, remove the container, run the same command; the volume carries everything
over. `api` and `gateway` are stateless. Restart a worker when it is idle, or let its turns fail
over: a worker that stops heartbeating for forty-five seconds loses its turns in flight, which
are recorded as failed, and its sessions continue elsewhere from their last snapshot. Back up the
`hg` volume on one box; it holds everything:

```bash
docker run --rm -v hg:/data -v "$PWD":/backup alpine tar czf /backup/hg.tgz -C /data .
```

Next: [Initialize](initialize.md).
