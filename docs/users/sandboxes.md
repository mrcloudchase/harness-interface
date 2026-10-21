# Sandboxes

A sandbox is where a harness runs: an image, the hosts a run may reach besides its provider, and
limits. Nothing of harness-interface and nothing of any harness is in the image; the CLI arrives as
a tools layer the harness's own `install.sh` built.

```bash
curl -s -X PUT $HI/v1/sandboxes/node22 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"image": "node:22-bookworm-slim", "egress": ["github.com"], "memory": "4g", "pids": 512}'
```

| Field | Meaning |
|---|---|
| `image` | A public image reference, pulled once. Or: |
| `dockerfile` | A Dockerfile's text, built once per content. One of the two. |
| `egress` | Hosts a run may open TLS tunnels to, `host` or `host:port`, besides its provider. Empty is the usual answer. |
| `memory` | Docker's size, `4g`. |
| `pids` | The process limit. |

The image needs `bash` (every script runs under it) and whatever `install.sh` and the CLI need:
node for an npm-installed CLI, python for a pip-installed one, git if the harness clones. A
Dockerfile is the way to get exactly that:

```json
{"dockerfile": "FROM python:3.12-slim\nRUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/*\n"}
```

## What every run gets, whatever the image

- a fresh container, removed when the turn ends;
- no Linux capabilities, no privilege escalation, a read-only root, an unprivileged user,
  `/tmp` as memory;
- the harness folder and its tools layer read-only, the member's `$HOME` and the session's
  workspace and run directory read-write, nothing else of the host;
- an internal network with one way out, the door, which tunnels to `egress` hosts and refuses
  everything else, and resolves no names for the run;
- the provider through the gateway, with a session token instead of the key;
- the sandbox's memory and process limits, and the harness's wall-clock cap.

## Installs

The first time a harness runs in a sandbox, `install.sh` runs in that image with `HI_TOOLS` writable
and egress to `harness.json`'s `install.egress` (the package registries) plus the sandbox's own. The
result is cached per (harness version, image) and mounted read-only on every turn after. A new
harness version or a new image installs again.
