# Add providers

A provider is where a harness's model calls go, and the key that unlocks them. It is three
fields: a `name`, a `url` and a `key`. The server stores them and hands them to the harness, and
never interprets them itself. Each harness's run script decides which of its CLI's settings get
the url and key.

## Add one

```bash
hi provider add anthropic --url https://api.anthropic.com --key-env ANTHROPIC_API_KEY
```

There are three ways to give the key; none of them puts it on the command line:

| | |
|---|---|
| `--key-env VAR` | read it from an environment variable |
| no flag, in a terminal | `hi` prompts for it, without echoing |
| no flag, piped | `hi` reads it from stdin: `pass show anthropic \| hi provider add …` |

Over HTTP, the same thing is one PUT:

```bash
curl -X PUT localhost:8000/providers/anthropic -H 'content-type: application/json' \
  -d '{"name": "anthropic", "url": "https://api.anthropic.com", "key": "sk-ant-..."}'
```

Adding a provider under an existing name replaces it, and the next run uses the new url and key.

## The names the shipped harnesses expect

Each shipped harness names its provider in its `harness.json`. Add providers under these names
to run them as they ship:

| Name | url | Serves | Used by |
|---|---|---|---|
| `anthropic` | `https://api.anthropic.com` | Anthropic Messages | 16 harnesses, including Claude Code, Hermes, Pi, OpenCode |
| `openai` | `https://api.openai.com/v1` | OpenAI Responses and chat | Codex, CheetahClaws |
| `deepseek` | `https://api.deepseek.com/anthropic` | DeepSeek models in the Anthropic Messages shape | DeepSeek Harness, Kimi Code, MiniMax Code |
| `deepseek-openai` | `https://api.deepseek.com/v1` | DeepSeek models in the OpenAI chat shape | Grok CLI, Qwen Code |

The full list, harness by harness, is in [harnesses/README.md](../../harnesses/README.md).

## Run a harness on another provider

Any provider that serves the API shape a CLI speaks works. To run Claude Code on DeepSeek,
point its `provider` at a provider that serves the Anthropic Messages shape:

```bash
hi provider add deepseek --url https://api.deepseek.com/anthropic --key-env DEEPSEEK_API_KEY

# a copy of claude-code, under a new name, on the new provider
hi harness show claude-code | jq '.name = "claude-deepseek" | .provider = "deepseek"' \
  | curl -sX PUT localhost:8000/harnesses/claude-deepseek -H 'content-type: application/json' -d @-

hi run claude-deepseek/deepseek-chat "Write a haiku about a hermit crab."
```

The copy leaves the original `claude-code` as it was. The `/deepseek-chat` after the harness name
picks the model; the run script passes it to the CLI's model flag. To change a harness in place
instead, edit its folder and `hi harness add` it again.

## What the provider controls in a sandbox

A sandboxed run can reach its provider's host, and nothing else, unless its sandbox allows more
([sandboxes](sandboxes.md)). The host and port come from the provider's `url`: port 443 for
`https`, 80 for `http`, or the port written in the url.

## Keys at rest and in flight

- **Stored** in `~/.harness-interface/data/providers/` as files only you can read (mode 600).
- **Never returned:** `hi provider ls`, `hi provider show` and `GET /providers` show names and
  urls only.
- **In a run,** the key reaches the harness as an environment variable inside its container, and
  is never on a command line ([security](security.md)).

## List, show, remove

```bash
hi provider ls
hi provider show anthropic
hi provider rm anthropic
```

A harness whose provider is removed fails its next request with a 400 that names the missing
provider.
