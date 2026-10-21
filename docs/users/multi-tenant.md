# Multi-tenant setup

One server serves many orgs. Every record and every path lives under the org, every request carries
a member's key, and nothing an org makes is visible to another. A self-hosted box is the same server
with one org.

## Orgs

A hosted platform creates orgs with the admin key, `HI_ADMIN_KEY` in the server's environment,
typically from its sign-up flow:

```bash
curl -s -X POST $HI/v1/orgs -H "Authorization: Bearer $HI_ADMIN_KEY" -H 'content-type: application/json' \
  -d '{"name": "acme", "owner": "chase", "max_runs": 8}'
```

The answer holds the owner's first API key, shown once. `max_runs` is how many turns the org may
run at once; a request past it waits for a slot. `GET /v1/orgs` lists them. The admin key does
nothing else: it cannot read an org's data or make requests.

A self-hosted box skips the admin key: `harness-interface init --org acme --owner chase` creates
the one org directly.

## Members, roles and keys

A member has a name and a role, `owner` or `member`.

| | owner | member |
|---|---|---|
| register providers, sandboxes, harnesses | yes | no |
| read them | yes | yes |
| add members, mint anyone's keys, see every key | yes | no |
| mint and revoke their own keys | yes | yes |
| make requests, steer, cancel | yes | yes |
| see sessions | everyone's | their own |

Keys are `hi_…` secrets shown once; the server keeps a digest. Revoke one with
`DELETE /v1/keys/{id}`; it stops working at once. Mint a key per place a key is used (a laptop, a
CI job, a service) so one can be revoked without the others.

## What is per org, per member, per session

| Scope | Where it lives | What it is for |
|---|---|---|
| org | `providers/`, `sandboxes/`, `harnesses/<name>/<version>/`, the harness's `seeds/org/` | what every member runs with; `seeds/org` is copied into every `$HOME` on every turn |
| member | `sessions/<org>/<member>/<harness>/home/` | the member's own `$HOME` for that harness: seeded once from `seeds/user`, then the CLI's |
| session | `sessions/<org>/<member>/<harness>/<sid>/` | the workspace, the run directory, the responses and the trace |

The server copies seed files and never reads them. A CLI's own precedence between its global and
project settings applies unchanged, because the files are exactly where it expects them.

## Isolation

Every turn is a fresh container from the sandbox's image, as an unprivileged user, with the member's
home and the session's workspace mounted and nothing else of the host. Its network is an internal
one whose only exit is a door that admits the sandbox's egress hosts and the provider, which it
reaches through a gateway that holds the key. Two orgs never share a container, a network or a
directory. See [security](security.md).

## Running it hosted

- Put TLS and your sign-up in front; the server itself speaks plain HTTP on `HI_HOST:HI_PORT`.
- Give it `HI_MASTER_KEY` from your secret store rather than a file on disk.
- Back up `HI_DATA_DIR`: it is the whole state, and the master key is needed to use the providers in it.
- One server is one cell: one Docker host and one data directory. Scale by cells, routing each org
  to one.
