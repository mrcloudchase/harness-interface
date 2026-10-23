---
name: harnessgateway-setup
description: Set up harnessgateway, the multi-tenant harness platform, end to end and prove it works. Use when asked to deploy or configure harnessgateway, create a tenant, register a provider, fork or upload a harness package, add members and keys, or make a first OpenAI Responses request against it. Covers the one-box self-hosted platform and a tenant on a hosted one.
---

# Set up harnessgateway end to end

harnessgateway runs harness packages (a CLI agent plus `install.sh`, `request.sh`, `response.sh`
and seeds) in sandboxes it owns, behind the OpenAI Responses API. A tenant registers **providers**
(model endpoints and keys) and **harnesses** (packages, forked from the catalog or uploaded); members
`POST /v1/responses` with `model` set to the harness name or `harness/provider/model`.

Work the steps in order; each ends with a check. Never print, log or commit an API key, a provider
key, the deployer key or the master key: the platform shows each once and never again.

## 0. Which path

```bash
export HG="https://hg.example.com" KEY="…"
curl -s -o /dev/null -w "%{http_code}\n" $HG/v1/me -H "Authorization: Bearer $KEY"
```

| Result | Meaning | Go to |
|---|---|---|
| connection refused | no platform yet; you are the operator | 1 |
| `403` with an `hgd_…` key | the deployer key: it creates tenants and sees the fleet | 2 |
| `200`, `"role": "owner"` | a tenant owner's key | 3 |
| `200`, `"role": "member"` | a member's key: it can request, not register; ask an owner for 3 and 4 | 5 |
| `401` | unknown, revoked, or a suspended tenant | stop and ask |

`GET $HG/healthz` says whether sign-up is open; if it is and you have no key, `POST /v1/signup`
with `{"tenant": "<name>", "owner": "<your name>"}` returns an owner key once. Then go to 3.

## 1. Start the platform (operator)

Docker on the box, the data directory at the same path inside and out:

```bash
mkdir -p /srv/hg/data && cd deploy && docker compose --profile one-box up -d
docker compose exec platform harnessgateway init --tenant <tenant> --owner <owner>
```

`init` prints the deployer key and the owner's API key, once each. The home page is at `https://<HG_DOMAIN>`, the app at `/app`.
For many boxes, `docker compose --profile ha up -d` and workers that join with `HG_JOIN_TOKEN`;
`docs/deploy.md` and `docs/configuration.md` have the variables. Check: `curl -s $HG/healthz` returns `"status": "ok"`.

## 2. Create a tenant (deployer)

```bash
curl -s -X POST $HG/v1/tenants -H "Authorization: Bearer $HD_KEY" -H 'content-type: application/json' \
  -d '{"name": "<tenant>", "owner": "<owner>", "limits": {"max_runs": 4}}'
```

The reply's `key.secret` is the owner's key, once. Ceilings (`cpus`, `memory`, `pids`,
`run_timeout_s`, `install_timeout_s`, `max_runs`, `disk_mb`, `output_mb`, `upload_mb`) are the
deployer's to set, with `PATCH /v1/tenants/<name>`. Check: `GET /v1/tenants` lists it.

## 3. Register a provider (owner)

```bash
curl -s -X PUT $HG/v1/providers/<name> -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d "{\"url\": \"<https base url>\", \"api\": \"<shape>\", \"key\": \"$PROVIDER_KEY\"}"
```

| `api` | Typical `url` |
|---|---|
| `anthropic-messages` | `https://api.anthropic.com`, `https://api.deepseek.com/anthropic` |
| `openai-chat` | `https://api.openai.com/v1`, `https://api.deepseek.com/v1` |
| `openai-responses` | `https://api.openai.com/v1` |
| `none` | an endpoint of your own that adds its credential; `key` empty |

One provider per shape. The catalog packages expect providers named `deepseek` (Anthropic shape),
`deepseek-openai` and `openai` (OpenAI chat) or `openai-responses`; register under those names, or
name yours in the model path. Check: `GET /v1/providers/<name>` returns name, url and api, no key.

## 4. Add a harness (owner)

Fork from the catalog, the verified way:

```bash
curl -s $HG/v1/catalog -H "Authorization: Bearer $KEY"        # names, checks passed, notes
curl -s -X PUT $HG/v1/harnesses/<name> -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"catalog": "<package>"}'
```

Or upload your own: a folder with `harness.json` (contract 5: `defaults` provider and model,
`provider_env` names, `interrupt`, `install.egress`, `run.egress`, timeouts), `install.sh` (puts the
CLI under `$HG_TOOLS`), `request.sh` (the turn: prompt on stdin, prints the output), optional
`response.sh` (prints the response, exits with the status), `seeds/`. `tar czf <name>.tgz -C <name> .`
and `PUT /v1/harnesses/<name>` with the archive as the body; a `400` names what is wrong.
`docs/packages.md` is the contract. Check: `GET /v1/harnesses/<name>` shows a `version`.

## 5. Make the first request

```bash
curl -s $HG/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "<name>", "input": "Create hello.txt containing the word hello, then reply with the one word: done"}'
```

The first run installs the CLI once (minutes). `status` is `completed` when the package exited 0;
`output[0]` is what the package returned; `?detail=true` on `GET /v1/responses/<id>` shows the raw
streams; `metadata.session_id` is the session. Continue with `previous_response_id`, stream with
`"stream": true`, poll with `"background": true`. Then prove the session kept its work:

```bash
curl -s $HG/v1/sessions/<sid>/archive -H "Authorization: Bearer $KEY" -o ws.tgz && tar tzf ws.tgz | grep hello.txt
```

With the repository, `python scripts/live.py --url $HG --key $KEY --harness <name>` runs all nine checks.

## 6. Members and keys (owner)

```bash
curl -s -X POST $HG/v1/members -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"name": "<member>"}'
curl -s -X POST $HG/v1/members/<member>/keys -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"label": "laptop"}'
```

Members request and see their own sessions; owners see everyone's. `DELETE /v1/keys/<id>` revokes.

## When something fails

| Symptom | Fix |
|---|---|
| `404 no provider x` on a request | register the provider the package's defaults name, or use `harness/provider/model` |
| `error` starts `install.sh exited` | read the log tail in the message; a refused host means it is missing from `install.egress` |
| `error` is `the package exited N` | `?detail=true` for stderr; a 401 from the provider means the CLI sent its own key, not the session token |
| `status: incomplete` | past `run.timeout_s`; raise it within the tenant's ceiling |
| `409 … is running a response` | one turn at a time per session; wait or cancel |
| `the worker running it was lost` | the session continues from its snapshot; the deployer checks `GET /v1/workers` |
