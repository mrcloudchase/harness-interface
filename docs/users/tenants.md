# Tenants

One platform serves many tenants. Every record and every blob lives under the tenant, every request
carries a member's key, and nothing a tenant makes is visible to another. A self-hosted installation
is the same platform with one tenant, or with one tenant per team.

## How a tenant comes to exist

- **Hosted (`HI_SIGNUP=open`).** The front door is a sign-up: `POST /v1/signup` with `{"tenant":
  "acme", "owner": "chase"}`, or the form on the console. The answer holds the owner's first API key,
  shown once.
- **Self-hosted (`HI_SIGNUP=closed`, the default).** The deployer creates tenants: `POST /v1/tenants`
  with the deployer key, or `harness-interface init --tenant acme --owner chase` on the box. The
  deployer's console lists tenants and shows usage: counts, seconds, calls, bytes. Never prompts,
  output, packages or keys.

## Members, roles and keys

| | owner | member |
|---|---|---|
| register providers and packages | yes | no |
| read them | yes | yes |
| add members, mint anyone's keys, see every key | yes | no |
| mint and revoke their own keys | yes | yes |
| make requests, steer, cancel | yes | yes |
| see sessions | everyone's | their own |

Keys are `hi_…` secrets shown once; the platform keeps a digest. Revoke one with
`DELETE /v1/keys/{id}`. Mint a key per place a key is used so one can be revoked without the others.

## Ceilings

What a tenant's turns may use is set on the tenant by the deployer, never by the tenant:

| Ceiling | Default | Meaning |
|---|---|---|
| `cpus`, `memory`, `pids` | 2, 4g, 512 | per sandbox |
| `run_timeout_s`, `install_timeout_s` | 3600, 1200 | the most a package may ask for a turn or its install |
| `max_runs` | 4 | turns at once, across the tenant |
| `disk_mb` | 2048 | a session's workspace or home, snapshotted |
| `output_mb` | 16 | of a turn's output kept in its record |
| `upload_mb` | 64 | a package, or a request's files |

`PATCH /v1/tenants/{name}` with `{"limits": {…}}` changes them; `{"status": "suspended"}` refuses
the tenant's keys until it is active again. A member sees their tenant's ceilings at `GET /v1/me`.

## What is per tenant, per member, per session

| Scope | Where | What for |
|---|---|---|
| tenant | providers, packages, the package's `seeds/org/` | what every member runs with; `seeds/org` lands in every `$HOME` every turn |
| member | the home for each package, snapshotted per member | the CLI's own state: seeded once from `seeds/user`, then the CLI's |
| session | the workspace, snapshotted after each turn | where `request.sh` runs; what the archive returns |

Two members of one tenant never share a home; two sessions never share a workspace; two tenants
never share a uid, a network or a directory.
