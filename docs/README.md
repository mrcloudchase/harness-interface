# harness-interface documentation

harness-interface is an API server that runs coding harnesses (Claude Code, Codex, Hermes, Pi and
19 more) behind one endpoint, each run in its own sandbox. `hi` is its command line.

**New here?** Start with [Getting started](getting-started.md). In about ten minutes you go from
nothing installed to a conversation you've continued.

## Learn

| | |
|---|---|
| [Getting started](getting-started.md) | install, run a harness, continue the conversation, read what it did |

## How-to guides

| | |
|---|---|
| [Install, upgrade and uninstall](guides/install.md) | requirements, the installer, pinning a version, running from source |
| [Add providers](guides/providers.md) | add a model provider, handle keys, run a harness on another provider |
| [Use and write harnesses](guides/harnesses.md) | the shipped harnesses, and how to wrap any CLI as your own |
| [Customize sandboxes](guides/sandboxes.md) | add tools or hosts a harness needs, with your own Dockerfile |
| [Call the API from code](guides/api-clients.md) | curl, Python, the OpenAI SDK, streaming, continuing, cancelling |
| [Run harnesses in a loop](guides/loops.md) | stop prompting: a loop that builds a project from a spec and its tests |
| [Troubleshoot](guides/troubleshooting.md) | what an error means, and what to do about it |

## Reference

| | |
|---|---|
| [CLI](reference/cli.md) | every `hi` command, flag and exit code |
| [HTTP API](reference/http-api.md) | endpoints, the request and response wire format, streaming, errors |
| [Harness contract](reference/harness-contract.md) | `harness.json`, templates, and what a harness gets and gives back |
| [Configuration](reference/configuration.md) | environment variables, runtimes, where data lives |

## Concepts

| | |
|---|---|
| [Architecture](concepts/architecture.md) | the pieces, the life of a request, many runs at once, the code layout |
| [Security](concepts/security.md) | the sandbox, the egress door, keys, and what is and isn't protected |

The shipped harnesses, the provider each one expects and notes on each are in
[harnesses/README.md](../harnesses/README.md).
