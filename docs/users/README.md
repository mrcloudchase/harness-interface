# User docs

harness-interface runs harness packages in sandboxes behind the OpenAI Responses API. A tenant
registers providers and packages; its members make requests; a worker runs the package; the
gateway relays its provider calls and holds the keys.

| Read | When |
|---|---|
| [Getting started](getting-started.md) | You want a platform running and a first request answered, in ten minutes. |
| [Deploying](deploying.md) | One box or many; the roles, the backends, the data directory, TLS, capacity. |
| [Tenants](tenants.md) | Sign-up or the deployer's console; members, roles, keys, ceilings. |
| [Providers](providers.md) | A model endpoint and its key, and how the gateway uses them. |
| [Harness packages](packages.md) | The contract: `harness.json`, `install.sh`, `request.sh`, `response.sh`, `seeds/`. |
| [The catalog](harnesses/) | The shipped packages, one page each, with what was verified. |
| [Requests](requests.md) | The Responses API: the model path, files in, streaming, sessions, steer, cancel, traces, captures. |
| [Security](security.md) | The invariants, and the test that proves each. |
| [API reference](api.md) | Every route, in one table. |
| [Configuration](configuration.md) | The `HI_*` variables. |
| [Troubleshooting](troubleshooting.md) | What a failed response says and what to do. |
| [Setup skill](../../skills/harness-interface-setup/SKILL.md) | A SKILL.md for a coding agent that sets all of this up. |
