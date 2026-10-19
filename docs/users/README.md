# Using harness-interface

harness-interface runs coding harnesses (Claude Code, Codex, Hermes, Pi and 19 more, or your own)
in a sandbox. Use it three ways:
- **`hi`**, the command line, to run harnesses from a terminal;
- **the server**, an OpenAI Responses-compatible HTTP API, from any language or the OpenAI SDK;
- **the library**, from Python, to run a harness with no server at all.

**New here?** Start with [Getting started](getting-started.md). In about ten minutes you go from
nothing installed to a conversation you've continued.

## Guides

| | |
|---|---|
| [Getting started](getting-started.md) | install, run a harness, continue the conversation, read what it did |
| [How it works](how-it-works.md) | who owns what, the words, no new protocol, the three ways in, when it fits |
| [Install, upgrade and uninstall](install.md) | requirements, the installer, versions, running from source |
| [Providers](providers.md) | add a model provider, handle keys, run a harness on another provider |
| [Harnesses](harnesses.md) | the shipped harnesses, configuring them and bringing artifacts, and wrapping any CLI as your own |
| [Sandboxes](sandboxes.md) | add tools or hosts a harness needs, with your own Dockerfile |
| [Calling the API from code](api-clients.md) | curl, Python, the OpenAI SDK, streaming, continuing, cancelling, an agent on a harness |
| [The Python library](library.md) | run a harness, or anything else, in a sandbox from Python |
| [Loops](loops.md) | stop prompting: a loop that builds a project from a spec and its tests |
| [Troubleshooting](troubleshooting.md) | what an error means, and what to do about it |

## Reference

| | |
|---|---|
| [CLI](cli.md) | every `hi` command, flag and exit code |
| [HTTP API](api.md) | endpoints, the request and response format, streaming, errors |
| [Harness contract](harness-contract.md) | `harness.json`, templates, what a harness gets and gives back |
| [Configuration](configuration.md) | environment variables, runtimes, where data lives |
| [Security](security.md) | the sandbox, the egress door, keys, and what is and isn't protected |

The shipped harnesses, the provider each expects and notes on each are in
[harnesses/README.md](../../harnesses/README.md). To work on harness-interface itself, see
[docs/contributors](../contributors/README.md).
