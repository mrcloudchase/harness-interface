# Changelog

Every release is a section here, newest first, and the newest section's heading is the version.
A merge to `main` that adds a section releases it: the release workflow tags that version, builds
the wheel and the image, and publishes the section as its notes.

## [6.1.1]

- **Picky, updated.** The newest portrait on the home page and the sign-in page, and the small
  one next to the name is gone: the name is a wordmark, Harness in ink and Gateway in orange.
- **Picky rides in the rodeo.** A cowboy hat and a bandana on the Rodeo page, the home page's
  rodeo card and the rodeo's documentation.

## [6.1.0]

- **The arena is the rodeo.** The page, the records and the routes are named for it:
  `POST/GET/PATCH/DELETE /v1/rodeos`. The 6.0 paths under `/v1/arenas` keep answering, so
  nothing built on them breaks. A rodeo kept as an arena record before this release is not
  carried over.

## [6.0.1]

- **The base image's npm is current.** Node's bundled npm carried fixable findings (pacote,
  sigstore, ip-address, picomatch); the base image updates npm to the latest release, so the
  scan the base-image workflow runs after publishing passes.
- **Picky has a portrait.** The mascot is the illustrated hermit crab, with its shell, everywhere:
  the home page, the app, the documentation, the README and the favicon.

## [6.0.0]

**HarnessGateway** has accounts, and the app is new. A major because `POST /v1/signup` is gone:
sign-up is an account now.

- **Accounts.** A person signs up with an email and a password, or arrives from GitHub or Google
  (`HG_GITHUB_CLIENT_ID`/`_SECRET`, `HG_GOOGLE_CLIENT_ID`/`_SECRET`). With `HG_SMTP_URL` set, a
  sign-up verifies its email and a password can be reset by mail. Sign-up is open to everyone
  with `HG_SIGNUP=open` and to invited emails always; an account with no tenant gets one of its
  own. Owners invite by email (`/v1/invites`). The app's session is a signed cookie, accepted by
  every member route in place of a key. Routes under `/auth`.
- **The workspace in the app.** `GET /v1/sessions/{id}/files` and `…/files/{path}` read the
  workspace's files from its last snapshot; the Requests and Sessions pages show them as a tree
  with a viewer.
- **The arena.** `POST /v1/arenas` records one task run by several harnesses and the winner you
  pick (`PATCH`); `GET /v1/arenas` lists them with a leaderboard. The Arena page runs the turns
  side by side as they stream.
- **The app and the home page, redesigned.** Off-white, navy, orange and blue; a sidebar; the
  name is HarnessGateway. The documentation wears the same.
- The release and base-image workflows name the image after the repository, so a transfer to an
  organization needs no edit.

## [5.2.0]

- **The first boot makes the keys.** An `api` that starts with no deployer key sets one; with
  sign-up closed and no tenant, it creates the tenant `HG_TENANT` (`main`) with its owner
  `HG_OWNER` (`owner`) and the owner's API key. All three are printed once, to the log:
  `docker logs hg`. The second boot makes nothing. `init` remains, for a new deployer key or
  another tenant by hand.
- **The sandbox base image is pulled, not built.** With `HG_BASE_IMAGE` empty a node pulls
  `ghcr.io/mrcloudchase/harnessgatewayai-base`, published for amd64 and arm64 by the base-image
  workflow, and builds the shipped Dockerfile itself only when the pull fails. The first start
  takes seconds, not minutes.

## [5.1.0]

The deploy is one command:

```
docker run -d --name hg -p 127.0.0.1:8000:8000 -v /var/run/docker.sock:/var/run/docker.sock -v hg:/data ghcr.io/mrcloudchase/harnessgatewayai
```

- **The platform finds its own place.** A node that runs turns inspects its own container through
  the socket it was given: where the daemon keeps the paths behind its mounts, which network it is
  on, its address there. Every mount a sandbox gets is translated to the daemon's path, and the
  turn runner, the door and the CA bundle are copied under `<data>/worker/platform` first, so
  nothing of the platform container's own filesystem is shared. The data directory no longer has
  to be at the same path inside and out; a named volume is enough, on a Mac as on a server.
- **The gateway needs no port.** A sandbox's door is put on the platform container's own network
  and reaches the gateway at that container's address. `HG_GATEWAY_URL` is for a worker on another
  machine, where it names the gateway behind your load balancer; on a host process it still
  defaults to `host.docker.internal`.
- **Each turn's token lives under the data directory** (`<data>/worker/secrets`), not in the
  platform's temporary directory, so the sandbox can mount it wherever the platform runs.
- **The image is tested as it is deployed.** The Docker tests run the platform image with the
  socket, a volume and one port, create a tenant, a provider and a package through it, and take
  two turns, one of them through the gateway.
- In 5.0.x a platform run as a container could not start a single sandbox: the scripts and the
  token it mounted were paths in its own filesystem, which the host's daemon does not have.

## [5.0.1]

- **The image is `ghcr.io/mrcloudchase/harnessgatewayai`**, the repository's name, built for
  amd64 and arm64; the base image is `ghcr.io/mrcloudchase/harnessgatewayai-base`, the same.
- **The one-box platform's gateway port is reachable from its sandboxes.** The quickstart and the
  compose file published 8081 on 127.0.0.1 only, which `host.docker.internal` cannot reach, so a
  platform run as a container could not relay a single provider call. It is published on every
  interface now; the gateway answers nothing without a per-turn token.
- **The quickstart uses a directory under your home**, which works on a Mac, where `/srv` is
  read-only, as well as on a Linux box.

## [5.0.0]

The platform is **Harness Gateway** (harnessgateway.ai). Everything public is renamed, so this is
a major: the package and command are `harnessgateway`, the variables are `HG_*`, keys are `hg_…`
(members), `hgd_…` (the deployer) and `hgw_…` (workers), the image is
`ghcr.io/mrcloudchase/harnessgatewayai`, the data directory is `~/.harnessgateway`. Nothing on disk
from 4.x is read; a 4.x data directory is not migrated.

- **Contract 5.** The same package contract as 4 with the platform's variables renamed: `HG_DIR`,
  `HG_WORKSPACE`, `HG_REQUEST`, `HG_PROVIDER_URL`, `HG_PROVIDER_KEY_FILE`, `HG_STDOUT`, `HG_EXIT`,
  `HG_OUTCOME` and the rest; the provider alias inside a sandbox is `hg-provider`, the token file
  `/run/hg/token`. A package declares `"contract": 5`. The catalog is on it.
- **The web surface.** A home page at `/`, the documentation at `/docs`, and the app at `/app`:
  sign in or sign up, then providers, harnesses, requests, sessions and members. Members see their
  own sessions; owners see the tenant's.
- **The deployer's dashboard.** Tenants, workers and slots, and the platform's usage all time and
  over the last 30, 60 and 90 days (turns, seconds, provider calls, bytes), charted per day and
  per tenant, from `GET /v1/usage?days=N`. Usage records carry the time of the turn.
- **Picky** is a scalable SVG.

## [4.0.0]

A rebuild as a platform. Tenants bring providers and harness packages; the platform runs a package
in a sandbox it owns and returns what the package decides. The same image is the hosted platform
and the self-hosted one. Nothing of 3.x carries over on the wire or on disk.

- **Tenants, not orgs.** `POST /v1/signup` creates a tenant when `HG_SIGNUP=open`; otherwise the
  deployer does, with a deployer key, and sets each tenant's ceilings (cpus, memory, pids, timeouts,
  runs at once, disk, output, upload). A tenant configures two things: providers and harnesses.
- **No sandboxes resource.** One platform-built base image for every turn; a package carries its
  own egress (`install.egress`, `run.egress`); the request's `model` is `harness` or
  `harness/provider/model`.
- **Contract 5.** `response.sh` decides what the response carries, from `request.sh`'s captured
  streams, exit code and outcome; without it the response is `request.sh`'s stdout. The whole
  request is in `$HG_REQUEST`. A steer reaches `request.sh` alone. `SIGTERM` is a stop, never a steer.
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
- **Containment.** A uid per tenant, cpu limits, an optional sandboxed runtime (`HG_RUNTIME`), a
  door that refuses private addresses after resolution and connects to the checked address, the
  platform's own writes into sandbox trees through a symlink-refusing helper, `install.sh`
  unprivileged, body and output caps, no tenant-chosen images or limits.
- **The console** at `/`: sign-up or sign-in, providers, harnesses and the catalog, sessions with live
  output, steer and cancel, members and keys; the deployer's fleet, tenants and workers.
- **Deploy.** One image (`deploy/Dockerfile`), one compose file with a one-box profile (SQLite, a
  directory, Caddy) and an HA profile (Postgres, MinIO, replicas, workers), a cloud-init for worker
  machines, a scheduled build and scan of the base image. No cloud SDK anywhere.
