# Changelog

Every release is a section here, newest first, and the newest section's heading is the version.
A merge to `main` that adds a section releases it: the release workflow tags that version, builds
the wheel and the image, and publishes the section as its notes.

## [4.0.0]

A rebuild as a platform. Tenants bring providers and harness packages; the platform runs a package
in a sandbox it owns and returns what the package decides. The same image is the hosted platform
and the self-hosted one. Nothing of 3.x carries over on the wire or on disk.

- **Tenants, not orgs.** `POST /v1/signup` creates a tenant when `HI_SIGNUP=open`; otherwise the
  deployer does, with a deployer key, and sets each tenant's ceilings (cpus, memory, pids, timeouts,
  runs at once, disk, output, upload). A tenant configures two things: providers and harnesses.
- **No sandboxes resource.** One platform-built base image for every turn; a package carries its
  own egress (`install.egress`, `run.egress`); the request's `model` is `harness` or
  `harness/provider/model`.
- **Contract 4.** `response.sh` decides what the response carries, from `request.sh`'s captured
  streams, exit code and outcome; without it the response is `request.sh`'s stdout. The whole
  request is in `$HI_REQUEST`. A steer reaches `request.sh` alone. `SIGTERM` is a stop, never a steer.
- **The catalog.** Twenty-two verified packages ship with the platform; `PUT /v1/harnesses/{name}`
  with `{"catalog": "<package>"}` forks one. A template package to start from.
- **Roles.** `api`, `gateway`, `worker`, or `all`. Workers join with a token, pull turns over HTTPS,
  fetch and push blobs through URLs good for one object, and hold no key, database or bucket
  credential. A worker that stops heartbeating loses its turns, not its sessions.
- **Backends.** Records in one table on SQLite or Postgres; blobs in a directory or any S3-API
  store. The suite runs on both.
- **The gateway as a service.** The one process where a provider key is in the clear; it swaps the
  per-turn session token for the key, relays only the API shape's endpoints, meters calls and bytes,
  and captures every exchange for the tenant (`GET /v1/responses/{id}/captures`).
- **Containment.** A uid per tenant, cpu limits, an optional sandboxed runtime (`HI_RUNTIME`), a
  door that refuses private addresses after resolution and connects to the checked address, the
  platform's own writes into sandbox trees through a symlink-refusing helper, `install.sh`
  unprivileged, body and output caps, no tenant-chosen images or limits.
- **The console** at `/`: sign-up or sign-in, providers, harnesses and the catalog, sessions with live
  output, steer and cancel, members and keys; the deployer's fleet, tenants and workers.
- **Deploy.** One image (`deploy/Dockerfile`), one compose file with a one-box profile (SQLite, a
  directory, Caddy) and an HA profile (Postgres, MinIO, replicas, workers), a cloud-init for worker
  machines, a scheduled build and scan of the base image. No cloud SDK anywhere.
