<p align="center">
  <img src="docs/media/picky.png" width="240" alt="Picky, the harness-interface mascot: a hermit crab with no shell of its own">
</p>

# harness-interface

A multi-tenant platform that runs coding-agent CLIs, the **harnesses**, one turn at a time in
sandboxes it owns, and exposes them as the **OpenAI Responses API**. A tenant brings two things: its
**providers** (model endpoints and their keys, sealed on arrival) and its **harness packages**
(`harness.json`, `install.sh`, `request.sh`, `response.sh`, `seeds/`: how to install a CLI, how to
run one turn, and what to return). The platform decides nothing about the output; it carries bytes in
and bytes out and says whether the turn ended well.

```
                    OpenAI Responses API (any SDK)
                                 │
   api (stateless) ─── records (SQLite | Postgres) ─── blobs (directory | S3)
   gateway (holds the keys, relays provider calls, meters, captures)
                                 │  turns, pulled over HTTPS
   workers (any Docker host) ─── a fresh sandbox per turn: the tenant's uid, no capabilities,
                                 read-only root, a door as its only route out
```

Twenty-two harnesses ship in the catalog, each run through a nine-check live suite against the
platform on DeepSeek or OpenAI: Claude Code, Codex, Hermes Agent, pi, OpenCode, Kilo CLI, Qwen
Code, Cline, Oh My Pi, goose, Kimi Code, MiniMax Code, aider, OpenHands, Grok Build, CheetahClaws,
MiMo Code, jcode, OpenSquilla, nanobot, zeroclaw and the DeepSeek Harness. Nineteen pass every
check; three pass all but what their CLI cannot do, [documented on their pages](docs/users/harnesses/).
A tenant forks one with one call and edits it, or uploads its own.

The same image is the hosted platform and the self-hosted one: `HI_SIGNUP=open` puts a sign-up page
on the front door; closed, the deployer creates tenants. One box runs every role over SQLite and a
directory; many boxes run `api,gateway` behind a load balancer with workers that join by token over
Postgres and any S3. No cloud SDK is imported anywhere.

- [Getting started](docs/users/getting-started.md): a platform, a tenant, a provider, a package and a
  request, in ten minutes.
- [Deploying](docs/users/deploying.md): one box, many boxes, and what each role needs.
- [Harness packages](docs/users/packages.md): the contract, and [the catalog](docs/users/harnesses/).
- [Requests](docs/users/requests.md), [security](docs/users/security.md), [the API](docs/users/api.md),
  [configuration](docs/users/configuration.md), [troubleshooting](docs/users/troubleshooting.md).
- [For contributors](docs/contributors/): the layers, the conventions, the release.

A skill for coding agents that sets it all up is at [`skills/harness-interface-setup/SKILL.md`](skills/harness-interface-setup/SKILL.md).

Apache-2.0.
