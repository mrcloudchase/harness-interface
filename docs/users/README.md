# User docs

harness-interface is a multi-tenant harness server. An org registers its model providers, its
sandboxes and its harness folders; its members drive those harnesses through the OpenAI Responses
API, stateful or stateless, and get everything the harness printed back. The server runs the script,
relays the bytes and remembers both; it knows nothing about any CLI.

| Read | When |
|---|---|
| [Getting started](getting-started.md) | You want a server running and a first request answered, in ten minutes. |
| [Multi-tenant setup](multi-tenant.md) | You host it for many orgs, or run it self-hosted for one. Orgs, members, keys, roles, quotas. |
| [Providers](providers.md) | Adding a model endpoint and its key. |
| [Sandboxes](sandboxes.md) | Adding an image or a Dockerfile, egress and limits. |
| [The harness template](harness-template.md) | The folder: `harness.json`, `install.sh`, `request.sh`, `seeds/`; a table of verified harnesses, each with [its own page](harnesses/). |
| [Requests](requests.md) | The Responses API: overrides, files in, output and artifacts out, sessions, steer, cancel, traces. |
| [Building on it](building-on-it.md) | Interactive sessions, agents, loops and a software factory, as programs against the API. |
| [Security](security.md) | What a sandbox can reach, where keys live, what to protect. |
| [API reference](api.md) | Every route, in one table. |
| [Configuration](configuration.md) | The server's environment variables. |
| [Troubleshooting](troubleshooting.md) | What a failed response says and what to do. |
| [Setup skill](../../skills/harness-interface-setup/SKILL.md) | A SKILL.md to hand your coding agent so it sets all of this up for you, end to end. |
