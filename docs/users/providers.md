# Providers

A provider is a model endpoint: its base URL, the API shape its credential travels in, and its
key. Owners register them; every member's requests may name them.

```bash
curl -s -X PUT $HI/v1/providers/anthropic -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.anthropic.com", "api": "anthropic-messages", "key": "sk-ant-…"}'
```

| Field | Meaning |
|---|---|
| `url` | `https://host[/path]`, the base the CLI's own SDK would take. |
| `api` | `anthropic-messages` (the key goes in `x-api-key`), `openai-responses` or `openai-chat` (`Authorization: Bearer`), or `none`. |
| `key` | The credential. Sealed on arrival; `GET` never returns it. Empty only with `api: none`. |

`api: none` is for an endpoint that adds the credential itself: your own proxy, or a gateway that
authenticates by network. The server then holds no secret for that provider at all.

Examples:

```json
{"url": "https://api.openai.com/v1", "api": "openai-responses", "key": "sk-…"}
{"url": "https://api.deepseek.com/anthropic", "api": "anthropic-messages", "key": "sk-…"}
{"url": "https://openrouter.ai/api/v1", "api": "openai-chat", "key": "sk-or-…"}
{"url": "https://llm-proxy.internal.example", "api": "none", "key": ""}
```

## How a run reaches it

A run never holds the key. It gets the gateway's URL in `HI_PROVIDER_URL` (and in the variable
`harness.json` names as `provider_env.url`) and a session token in `HI_PROVIDER_KEY_FILE` (and
`provider_env.key`). The CLI calls the gateway with the token exactly as it would call the provider
with a key; the gateway, a process started for that one run, swaps the token for the key and
forwards over TLS. The token is worthless anywhere else and dies with the run.

A harness decides what to do with the two variables in its `request.sh`. For Claude Code,
`ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` are enough; for Codex, a `model_providers` entry in
its config.

## Which provider a request uses

`harness.json` names a default; a request overrides it with `metadata.provider`. The provider must
serve the API shape the CLI speaks: Claude Code speaks Anthropic Messages, so it needs an
`anthropic-messages` provider, which DeepSeek, Anthropic and most aggregators offer. A model name
goes with it: `metadata.model`, or the harness's default, reaches the run as `HI_MODEL`.
