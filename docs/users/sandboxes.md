# Customize sandboxes

A sandbox is a Dockerfile, plus any hosts a run may reach besides its provider. Every harness
names the sandbox it runs in. With the Docker runtime, each run is a fresh container from that
sandbox's image.

## The default sandbox

`default` is built in, and every shipped harness uses it. It contains:
- Node 22 and Python 3, with git, curl and uv;
- the CLI of every shipped harness, pinned where its publisher allows;
- an unprivileged user, uid 1000.

```bash
hi sandbox show default | jq -r .dockerfile     # its Dockerfile
```

It can't be replaced or removed. Its image builds on the first run that needs it, which takes a
few minutes and about 10 GB, and every run after that reuses it.

## When to add one

Add a sandbox when a harness needs something `default` doesn't have:
- a tool or language, such as a compiler, a database client, or your own CLI;
- another host to reach, such as a package index or an internal API;
- a smaller image, with only what one harness needs.

## Write the Dockerfile

The one rule: **give the image an unprivileged user with uid 1000.** A server running as root hands
the workspace to that uid before each run, so the harness can write to it. A server running as
your own user runs the container as you instead, so the workspace is already writable.

A harness puts its CLI's home in the workspace itself (`"HOME": "{workspace}/.home"` in its
`harness.json`), so the CLI's state survives between turns. The image needs no `HOME` or `WORKDIR`
of its own: the workspace is mounted at its own path and is the working directory.

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir my-cli==1.4.0
RUN useradd --create-home --uid 1000 runner
USER runner
```

You don't need to lock anything down in the Dockerfile. Every run gets the same hardening, whatever
its image ([security](security.md)).

## Add it

```bash
hi sandbox add python-dev ./python-dev.Dockerfile --egress pypi.org files.pythonhosted.org
```

Then point a harness at it: set `"sandbox": "python-dev"` in its `harness.json`, and add the
harness again.

## Allow more hosts

A run can always reach its provider's host. `--egress` adds hosts on top of that. Each one can
be written three ways:

| Written as | Means |
|---|---|
| `pypi.org` | `pypi.org`, port 443 |
| `registry.internal:8443` | that host and port |
| `https://api.example.com/v2` | that URL's host and port |

Everything else stays unreachable: other hosts, other ports, and plain HTTP.

## Rebuilds

An image is named after a hash of its Dockerfile, so:
- **Changing the Dockerfile** (`hi sandbox add` again) builds a new image on the next run that
  uses the sandbox.
- **Re-adding it unchanged** reuses the image that's already built.
- **Build logs** are in `~/.harness-interface/data/logs/build-<sandbox>-<hash>.log`. A build that
  fails ends that run `failed`, with `setup_failed` and the end of the log.
- **Old images** stay until you remove them: `docker images 'harness-interface/*'`.

## Remove one

```bash
hi sandbox rm python-dev
```

A harness that still names the sandbox fails its next request with a 400 that names the missing
sandbox.
