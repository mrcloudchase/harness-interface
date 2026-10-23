# Configuration

Every role reads the same variables, each with a default, when the process starts.

| Variable | Default | Meaning |
|---|---|---|
| `HG_HOST`, `HG_PORT` | `127.0.0.1`, `8000` | where `api` listens |
| `HG_PUBLIC_URL` | `http://127.0.0.1:8000` | how workers reach the API and where signed blob URLs point, for the directory backend |
| `HG_DATA_DIR` | `~/.harnessgateway` | the data directory: the master key file, SQLite and blobs on one box; worker caches everywhere |
| `HG_RECORDS` | `sqlite:///<data>/records.db` | or `postgresql://user:pass@host/db` |
| `HG_BLOBS` | `dir:///<data>/blobs` | or `s3://bucket`, with `HG_S3_ENDPOINT` and `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| `HG_MASTER_KEY`, `HG_MASTER_KEY_FILE` | the file the first boot wrote under the data directory | 64 hex digits that seal provider keys and sign blob URLs |
| `HG_SIGNUP` | `closed` | `open`: a sign-up creates tenants; `closed`: the deployer does |
| `HG_DEPLOYER_KEY` | the key the first boot or `init` set | overrides the stored deployer key; set, the first boot makes none |
| `HG_TENANT`, `HG_OWNER` | `main`, `owner` | the tenant and owner the first boot creates when sign-up is closed and there is no tenant |
| `HG_JOIN_TOKEN` | generated for the `all` role | what a worker presents to join |
| `HG_GATEWAY_HOST`, `HG_GATEWAY_PORT` | `0.0.0.0`, `8081` | where `gateway` listens |
| `HG_GATEWAY_URL` | found: the platform container's own address, or `host.docker.internal:8081` for a host process | how a sandbox's door reaches the gateway; set it to a TLS address for a worker on another machine |
| `HG_BASE_IMAGE` | empty: the shipped one, `ghcr.io/mrcloudchase/harnessgatewayai-base`, pulled once, built on the node when it cannot be | the sandbox image |
| `HG_RUNTIME` | empty | a sandboxed Docker runtime for every sandbox, such as `runsc` |
| `HG_ALLOW_PRIVATE` | `0` | `1`: egress and provider URLs may name private addresses, for an internal registry or model server on a self-hosted box |
| `HG_CA_FILE` | none | a CA bundle given to sandboxes and the door, where the network re-signs TLS |
| `HG_WORKER_NAME`, `HG_WORKER_SLOTS` | the hostname, `4` | the worker's name in the fleet and its turns at once |
| `HG_CONTROL_URL` | `HG_PUBLIC_URL` | the API, for a worker on another machine |
| `HG_CATALOG_DIR` | the shipped catalog | another catalog directory |

`harnessgateway serve --role api,gateway,worker` chooses the roles; `all` is the default.

## Where things are

| Path | Holds |
|---|---|
| `/` | the home page |
| `/app` | the app: sign in or sign up, then the tenant's tabs or the deployer's dashboard |
| `/web/…` | the app's files |
| `/docs/` | this documentation |
| `/reference` | the OpenAPI reference, interactive |
| `/healthz` | status, version, roles, whether sign-up is open |
| `/v1/…` | the API |
| `/internal/…` | the workers' routes and signed blob URLs |

## The data directory on one box

```
<data>/
  master.key        written by the first boot or init, mode 600
  records.db        SQLite: tenants, members, keys, providers, packages, sessions, turns, traces, usage
  blobs/            tenants/<tenant>/harnesses/…, sessions/<sid>/workspace.tgz, turns/<rid>/…, members/…/home.tgz
  worker/           the worker's caches
```

Back it up whole. A newer platform reads an older data directory.

Next: [Security](security.md).
