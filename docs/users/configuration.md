# Configuration

The server reads its environment when it starts.

| Variable | Default | Meaning |
|---|---|---|
| `HI_HOST` | `127.0.0.1` | Listen address. |
| `HI_PORT` | `8000` | Listen port. |
| `HI_DATA_DIR` | `~/.harness-interface/data` | Everything: orgs, keys, providers, sandboxes, harness versions, sessions, logs. |
| `HI_MASTER_KEY` | | 64 hex digits that seal provider keys. Or: |
| `HI_MASTER_KEY_FILE` | `<data>/master.key` if it exists | A file holding them; `init` writes one. |
| `HI_ADMIN_KEY` | unset | The platform key that creates orgs. Unset means no org can be created over the API. |
| `HI_CA_FILE` | unset | A CA bundle to trust inside sandboxes and doors, where a network re-signs TLS. |

`harness-interface init --org NAME --owner NAME [--data DIR] [--max-runs N]` creates the master
key file, the org and the owner's key. `harness-interface serve` runs the server.

Per org, `max_runs` (set at creation) is how many turns run at once. Per sandbox, `memory` and
`pids`. Per harness, `run.timeout_s`, `run.stop_timeout_s`, `install.timeout_s`.

Docker must be reachable by the server's user (`docker info`). The door's image is
`python:3.12-alpine`, pulled once.
