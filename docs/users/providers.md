# Providers

A provider is where a harness's model calls go: a name, a base URL, the API shape it serves, and its
key. The server keeps the key; a harness never gets it, only a way to call the provider through its
sandbox's gateway ([keys](security.md#keys)).

## Add one

```bash
python3 -c 'import json, os; print(json.dumps({"url": "https://api.anthropic.com",
  "api": "anthropic-messages", "key": os.environ["ANTHROPIC_API_KEY"]}))' \
| curl -s -X PUT localhost:8000/providers/anthropic -H 'content-type: application/json' -d @-
```

Building the body in a program keeps the key off the command line. From Python:
`sessions.registry.put_provider(ProviderEntry("anthropic", url, api, key))` ([library](library.md)).

| Field | |
|---|---|
| `url` | the base URL the shape's official SDK takes: `https://api.anthropic.com` for `anthropic-messages` (no version path), `https://api.openai.com/v1` for `openai-*` (with one). `https` only, no credentials, query or fragment. |
| `api` | the shape it serves: `anthropic-messages`, `openai-responses` or `openai-chat` |
| `key` | its API key; stored privately, never returned |

Putting a provider under an existing name replaces it; the next response uses the new one. `GET
/providers` lists them, without keys; `DELETE /providers/{name}` removes one.

Some that work:

| Provider | `url` | `api` |
|---|---|---|
| Anthropic | `https://api.anthropic.com` | `anthropic-messages` |
| OpenAI | `https://api.openai.com/v1` | `openai-responses` or `openai-chat` |
| DeepSeek, Anthropic shape | `https://api.deepseek.com/anthropic` | `anthropic-messages` |
| DeepSeek, OpenAI shape | `https://api.deepseek.com/v1` | `openai-chat` |

## Which provider a response uses

`model` in a request is `harness[@provider][/model]`:

| `model` | Provider | Model |
|---|---|---|
| `claude-code` | the one registered for the harness's default URL and shape | the CLI's default |
| `claude-code/claude-sonnet-4-6` | the same | `claude-sonnet-4-6` |
| `claude-code@deepseek/deepseek-chat` | `deepseek` | `deepseek-chat` |

Each folder's `harness.json` names a default (`provider.url` and `provider.api`) and every shape its CLI
speaks (`apis`). With no `@provider`, the server uses a registered provider whose URL and shape match
the default; if there is none, the request is a 400 that says what to register. A named provider must
serve a shape in `apis`. A session keeps its provider for its whole life.

So running Claude Code on DeepSeek is one word: register DeepSeek's Anthropic endpoint, and ask for
`claude-code@deepseek/deepseek-chat`. The shipped folders' shapes are in
[harnesses/README.md](../../harnesses/README.md).

## What a harness gets

`HI_PROVIDER_URL`, `HI_PROVIDER_API` and `HI_PROVIDER_KEY_FILE`, and the model as `HI_MODEL`. Under the
gateway (the default) the URL is the sandbox's gateway, `http://hi-provider:8080` plus the provider's
path, and the file holds a session token; the gateway swaps it for the key. A folder whose CLI can't
use a plain-HTTP base URL sets `"credential": "file"` in `run`: then the URL is the provider's own and
the file holds the key. Either way the folder's `run.sh` maps them onto the CLI's own settings.

The sandbox reaches the provider, and nothing else but the hosts a folder lists in `run.egress`.
