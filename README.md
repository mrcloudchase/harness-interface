<p align="center">
  <img src="docs/media/picky.png" width="240" alt="Picky, the harness-interface mascot: a hermit crab with no shell of its own">
</p>

<h1 align="center">harness-interface</h1>

<p align="center">
  <b>Run any coding harness behind one API, every run in its own sandbox.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/harnesses-23-e8590c" alt="23 harnesses">
  <img src="https://img.shields.io/badge/runs-sandboxed%20in%20Docker-2496ed" alt="Runs sandboxed in Docker">
  <img src="https://img.shields.io/badge/API-OpenAI%20Responses-412991" alt="OpenAI Responses API">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0"></a>
</p>

<p align="center">
  <a href="docs/getting-started.md">Getting started</a> ·
  <a href="docs/README.md">Docs</a> ·
  <a href="docs/reference/cli.md">CLI</a> ·
  <a href="docs/reference/http-api.md">API</a> ·
  <a href="harnesses/README.md">Harnesses</a>
</p>

---

**Meet Picky**, a hermit crab with no shell of its own. Hermit crabs don't grow shells; they find
one that fits, wear it, and swap it when they need to. Picky does that with coding harnesses:
Claude Code for one task, Codex for the next, then the one you wrote yourself.

That's harness-interface:
- **One API.** Call any harness by name, through the OpenAI Responses format. Continue its
  conversation with `previous_response_id`, and get its own output streamed back.
- **One sandbox per run.** Each run is a fresh, locked-down container that can reach its model
  provider and nothing else.

<table align="center">
  <tr>
    <td align="center"><b>Claude Code</b><br><img src="docs/media/run-claude-code.gif" width="420" alt="hi run claude-code: a haiku, then its title in the same conversation"></td>
    <td align="center"><b>Codex</b><br><img src="docs/media/run-codex.gif" width="420" alt="hi run codex: a haiku, then its title in the same conversation"></td>
  </tr>
  <tr>
    <td align="center"><b>Hermes</b><br><img src="docs/media/run-hermes.gif" width="420" alt="hi run hermes: a haiku, then its title in the same conversation"></td>
    <td align="center"><b>Pi</b><br><img src="docs/media/run-pi.gif" width="420" alt="hi run pi: a haiku, then its title in the same conversation"></td>
  </tr>
</table>
<p align="center"><sub>Same command, four harnesses: each writes a haiku, then titles it in the same conversation with <code>-c</code>.</sub></p>

## Quickstart

You need git, and Docker for sandboxed runs. The installer brings everything else.

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh

hi server start
hi provider add anthropic --url https://api.anthropic.com --key-env ANTHROPIC_API_KEY
hi harness add --builtin claude-code
hi run claude-code "Write a haiku about a hermit crab trying on shells."
hi run claude-code "Now give it a title." -c
```

The first run builds the sandbox image, which takes a few minutes. Every run after that starts in
seconds. [Getting started](docs/getting-started.md) walks through it.

## Supported harnesses

Every harness here ships with harness-interface, and has been run end to end: a first request,
then a continued second one, in the default sandbox. `hi harness add --builtin` registers them.

| Harness | Default provider | Runs | Continues |
|---|---|:-:|:-:|
| [Aider](harnesses/aider) | `anthropic` | ✅ | ✅ |
| [CheetahClaws](harnesses/cheetahclaws) | `openai` | ✅ | ✅ |
| [Claude Code](harnesses/claude-code) | `anthropic` | ✅ | ✅ |
| [Cline](harnesses/cline) | `anthropic` | ✅ | ✅ |
| [Codex](harnesses/codex) | `openai` | ✅ | ✅ |
| [DeepSeek Harness](harnesses/deepseek-harness) | `deepseek` | ✅ | ✅ |
| [Gajae Code](harnesses/gajae) | `anthropic` | ✅ | ✅ |
| [Goose](harnesses/goose) | `anthropic` | ✅ | ✅ |
| [Grok CLI](harnesses/grok-cli) | `deepseek-openai` | ✅ | ✅ |
| [harness-engineering](harnesses/harness-engineering) | `anthropic` | ✅ | ✅ |
| [Hermes](harnesses/hermes) | `anthropic` | ✅ | ✅ |
| [J-Code](harnesses/jcode) | `anthropic` | ✅ | ✅ |
| [Kilo Code](harnesses/kilo) | `anthropic` | ✅ | ✅ |
| [Kimi Code](harnesses/kimi-code) | `deepseek` | ✅ | ✅ |
| [MiMo Code](harnesses/mimo) | `anthropic` | ✅ | ✅ |
| [MiniMax Code](harnesses/minimax-code) | `deepseek` | ✅ | ✅ |
| [nanobot](harnesses/nanobot) | `anthropic` | ✅ | ✅ |
| [OMP](harnesses/omp) | `anthropic` | ✅ | ✅ |
| [OpenCode](harnesses/opencode) | `anthropic` | ✅ | ✅ |
| [OpenHands](harnesses/openhands) | `anthropic` | ✅ | ✅ |
| [OpenSquilla](harnesses/opensquilla) | `anthropic` | ✅ | ✅ |
| [Pi](harnesses/pi) | `anthropic` | ✅ | ✅ |
| [Qwen Code](harnesses/qwen-code) | `deepseek-openai` | ✅ | ✅ |

The provider is a default, not a limit. Any provider that speaks the API a CLI expects works:
Claude Code runs on DeepSeek by changing one word ([providers](docs/guides/providers.md)). Your
own CLI is two files away ([write a harness](docs/guides/harnesses.md#write-your-own)).

## Highlights

- **Any harness, one request shape.** `model` names the harness, `previous_response_id`
  continues it, and its own output streams back line for line.
- **Sandboxed by default.** No capabilities, a read-only root, and one network exit: the
  provider ([security](docs/concepts/security.md)).
- **Built for many clients.** Runs belong to the server: they run side by side, survive a client
  disconnecting, and can be cancelled at any point.
- **Everything recorded.** Each run keeps:
  - the harness's raw output and log;
  - its produced files;
  - its usage and cost;
  - the session to resume.
- **Built for loops.** Drive harnesses from a program, not by hand.
  [examples/build-loop](examples/build-loop/) builds a project from a spec and its tests:
  - it plans, builds, verifies in a container, reviews with a second harness, and checkpoints;
  - it escalates between harnesses, and stops cleanly at a deadline or budget.

  [Watch it run](docs/guides/loops.md#watch-one).
- **See everything.** Each harness's stdout and stderr stream live. Every file it adds, changes
  or deletes is recorded, and each turn's diff can be read, even while it's running.
- **Change anything live.** Add or change a provider, sandbox or harness, and the next request
  uses it. No restarts.
- **Small enough to read.** About 1,200 lines of Python. The sandbox and its egress door are
  about 250 of them.

## Use it from code

`hi` is one client. The API speaks the OpenAI Responses format, so the OpenAI SDK is another:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000", api_key="unused")
first = client.responses.create(model="claude-code", input="Write a haiku about a hermit crab.")
second = client.responses.create(model="claude-code", input="Now give it a title.",
                                 previous_response_id=first.id)
print(second.output_text)
```

curl, streaming and everything else: [Call the API from code](docs/guides/api-clients.md).

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | install, run a harness, continue it, read what it did |
| [How-to guides](docs/README.md#how-to-guides) | install, providers, harnesses, sandboxes, API clients, troubleshooting |
| [Reference](docs/README.md#reference) | the CLI, the HTTP API, the harness contract, configuration |
| [Concepts](docs/README.md#concepts) | architecture and security |

## Contributing

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
uv run --extra dev pytest          # no Docker or keys needed
uv run harness-interface           # the server, from source
```

New harnesses are welcome: a harness is a folder in [harnesses/](harnesses/), and the
[harness guide](docs/guides/harnesses.md) shows how to write one.

## Status

harness-interface is the base layer: one interface to any harness, and a record of everything
each one did. Today it is single-tenant: it runs on localhost, with no authentication. Next, built
on that same record:
- comparing harnesses on the same task;
- judging their output;
- routing each request to the right one.

## License

[Apache 2.0](LICENSE).
