# Using harness-interface

harness-interface runs coding harnesses (Claude Code, Codex, pi, OpenCode, Hermes, or your own) in a
sandbox, as sessions you can continue, steer and stop. Use it two ways:
- **the server**, an OpenAI Responses-compatible HTTP API, from any language or the OpenAI SDK;
- **the library**, from Python, with no server at all.

**New here?** Start with [Getting started](getting-started.md).

## Guides

| | |
|---|---|
| [Getting started](getting-started.md) | install, run a harness, continue its session, steer it |
| [How it works](how-it-works.md) | who owns what, the words, one response from start to end, when it fits |
| [Install, upgrade and uninstall](install.md) | requirements, the installer, running from source |
| [Providers](providers.md) | add a provider, and run a harness on any provider it can speak |
| [Harness folders](harnesses.md) | the shipped harnesses, config and work artifacts, and writing your own |
| [Calling the API from code](api-clients.md) | curl, the OpenAI SDK, streaming, interrupts, agents and loops |
| [The Python library](library.md) | the same, with no server |
| [Troubleshooting](troubleshooting.md) | what an error means, and what to do about it |

## Reference

| | |
|---|---|
| [HTTP API](api.md) | every route, the request and response, streaming, sessions |
| [Harness contract](harness-contract.md) | `harness.json`, what a harness is given and gives back |
| [Configuration](configuration.md) | environment variables, where data lives |
| [Security](security.md) | the sandbox, the egress door and gateway, keys, and what isn't protected |

The shipped harness folders are in [harnesses/](../../harnesses/README.md). To work on
harness-interface itself, see [docs/contributors](../contributors/README.md).
