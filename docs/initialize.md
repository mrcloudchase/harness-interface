# Initialize

A fresh platform has no keys. One command creates them.

```bash
docker exec hi harness-interface init --tenant acme --owner chase
```

```
master key written to /srv/hi/data/master.key
deployer key (shown once): hd_…
tenant acme created with owner chase
owner's API key (shown once): hi_…
```

Three things happened:

- **The master key** was written to the data directory with mode 600. It seals every provider key
  and signs blob URLs. On a fleet, give it to `api` and `gateway` as `HI_MASTER_KEY` instead, and
  the file is not written.
- **The deployer key** (`hd_…`) was set. It manages tenants, limits and workers, and nothing a
  tenant owns. It is shown once; `init` again replaces it.
- **A tenant** named `acme` was created with `chase` as its owner, and the owner's API key
  (`hi_…`) was shown once.

Keep both keys somewhere safe. The platform stores only their hashes and cannot show them again.

## Without a first tenant

`harness-interface init` alone sets the master and deployer keys. Create tenants later with the
deployer key, from the console's Tenants tab or the API:

```bash
curl -s -X POST https://hi.example.com/v1/tenants -H "Authorization: Bearer $HD_KEY" \
  -H 'content-type: application/json' -d '{"name": "acme", "owner": "chase"}'
```

The reply carries the owner's key once. [Tenants and limits](tenants.md) has the ceilings a
tenant can be given at creation.

## Open sign-up

With `HI_SIGNUP=open`, the sign-in page gains a "Create a tenant" card, and `POST /v1/signup`
creates a tenant with its first owner and returns the owner's key. New tenants get the default
ceilings; the deployer adjusts them afterwards. This is the hosted platform's shape; a
self-hosted team usually keeps sign-up closed and creates its one tenant with `init`.

## Check

```bash
curl -s http://127.0.0.1:8000/healthz
```

```json
{"status": "ok", "version": "4.0.0", "roles": ["api", "gateway", "worker"], "signup": "closed"}
```

Next: [Sign in](sign-in.md).
