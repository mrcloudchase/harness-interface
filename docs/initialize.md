# Initialize

A fresh platform has no keys. Its first boot makes them and prints them once.

```bash
docker logs hg
```

```
master key written to /data/master.key
first boot: shown once; `harnessgateway init` makes new ones
  deployer key: hgd_…
  tenant main created with owner owner
  owner's API key: hg_…
```

Three things happened:

- **The master key** was written to the data directory with mode 600. It seals every provider key
  and signs blob URLs. On a fleet, give it to `api` and `gateway` as `HG_MASTER_KEY` instead, and
  the file is not written.
- **The deployer key** (`hgd_…`) was set. It manages tenants, limits and workers, and nothing a
  tenant owns. With `HG_DEPLOYER_KEY` in the environment, none is made.
- **A tenant** named `main` was created with `owner` as its owner, and the owner's API key
  (`hg_…`) was shown. `HG_TENANT` and `HG_OWNER` choose the names. With `HG_SIGNUP=open`, no
  tenant is made: the sign-up page makes them.

Keep both keys somewhere safe. The platform stores only their hashes and cannot show them again;
the container's log holds them until the container is removed. The second boot makes nothing.

## Your account

The first boot gives you a key, not an account. To sign in by email on a self-hosted box, sign
in with the key, invite your own email from the Members page, sign out, and create your account
with that email. It lands in the tenant as a second owner. [The app](app.md) has the sign-in
methods and how to add GitHub or Google.

## By hand

```bash
docker exec hg harnessgateway init --tenant acme --owner chase
```

`init` sets a new deployer key, replacing the old one, and, with `--tenant`, creates that tenant
with its owner and prints the owner's key once. It is how a key is rotated, and how a platform
started with `HG_SIGNUP=open` gets a tenant without the sign-up page. More tenants come from the
deployer key, from the app's Tenants tab or the API:

```bash
curl -s -X POST https://hg.example.com/v1/tenants -H "Authorization: Bearer $HD_KEY" \
  -H 'content-type: application/json' -d '{"name": "acme", "owner": "chase"}'
```

The reply carries the owner's key once. [Tenants and limits](tenants.md) has the ceilings a
tenant can be given at creation.

## Open sign-up

With `HG_SIGNUP=open`, the app gains a "Create a tenant" card and the home page leads to it, and `POST /v1/signup`
creates a tenant with its first owner and returns the owner's key. New tenants get the default
ceilings; the deployer adjusts them afterwards. This is the hosted platform's shape; a
self-hosted team usually keeps sign-up closed and uses the tenant the first boot made.

## Check

```bash
curl -s http://127.0.0.1:8000/healthz
```

```json
{"status": "ok", "version": "5.2.0", "roles": ["api", "gateway", "worker"], "signup": "closed"}
```

Next: [The app](app.md).
