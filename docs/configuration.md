# Configuration

Every role reads the same variables, each with a default, when the process starts.

| Variable | Default | Meaning |
|---|---|---|
| `HI_HOST`, `HI_PORT` | `127.0.0.1`, `8000` | where `api` listens |
| `HI_PUBLIC_URL` | `http://127.0.0.1:8000` | how workers reach the API and where signed blob URLs point, for the directory backend |
| `HI_DATA_DIR` | `~/.harness-interface` | the data directory: the master key file, SQLite and blobs on one box; worker caches everywhere |
| `HI_RECORDS` | `sqlite:///<data>/records.db` | or `postgresql://user:pass@host/db` |
| `HI_BLOBS` | `dir:///<data>/blobs` | or `s3://bucket`, with `HI_S3_ENDPOINT` and `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` |
| `HI_MASTER_KEY`, `HI_MASTER_KEY_FILE` | the file `init` wrote under the data directory | 64 hex digits that seal provider keys and sign blob URLs |
| `HI_SIGNUP` | `closed` | `open`: a sign-up creates tenants; `closed`: the deployer does |
| `HI_DEPLOYER_KEY` | the key `init` set | overrides the stored deployer key |
| `HI_JOIN_TOKEN` | generated for the `all` role | what a worker presents to join |
| `HI_GATEWAY_HOST`, `HI_GATEWAY_PORT` | `0.0.0.0`, `8081` | where `gateway` listens |
| `HI_GATEWAY_URL` | `http://host.docker.internal:8081` | how a sandbox's door reaches the gateway; a TLS address across machines |
| `HI_BASE_IMAGE` | empty: the shipped one is built on the node | the sandbox image |
| `HI_RUNTIME` | empty | a sandboxed Docker runtime for every sandbox, such as `runsc` |
| `HI_ALLOW_PRIVATE` | `0` | `1`: egress and provider URLs may name private addresses, for an internal registry or model server on a self-hosted box |
| `HI_CA_FILE` | none | a CA bundle given to sandboxes and the door, where the network re-signs TLS |
| `HI_WORKER_NAME`, `HI_WORKER_SLOTS` | the hostname, `4` | the worker's name in the fleet and its turns at once |
| `HI_CONTROL_URL` | `HI_PUBLIC_URL` | the API, for a worker on another machine |
| `HI_CATALOG_DIR` | the shipped catalog | another catalog directory |

`harness-interface serve --role api,gateway,worker` chooses the roles; `all` is the default.

## Where things are

| Path | Holds |
|---|---|
| `/` | the console |
| `/docs/` | this documentation |
| `/reference` | the OpenAPI reference, interactive |
| `/healthz` | status, version, roles, whether sign-up is open |
| `/v1/…` | the API |
| `/internal/…` | the workers' routes and signed blob URLs |

## The data directory on one box

```
<data>/
  master.key        written by init, mode 600
  records.db        SQLite: tenants, members, keys, providers, packages, sessions, turns, traces, usage
  blobs/            tenants/<tenant>/harnesses/…, sessions/<sid>/workspace.tgz, turns/<rid>/…, members/…/home.tgz
  worker/           the worker's caches
```

Back it up whole. A newer platform reads an older data directory.

Next: [Security](security.md).
