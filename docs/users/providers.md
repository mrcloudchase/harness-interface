# Providers

A provider is a model endpoint and its key. The tenant registers it once; a package names it in its
defaults or a request names it in the model path; the platform injects it at run time.

```bash
curl -s -X PUT $HI/v1/providers/<name> -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.openai.com/v1", "api": "openai-chat", "key": "sk-…"}'
```

| Field | Meaning |
|---|---|
| `url` | `https://host[/path]`. Public hosts only; a private or link-local address is refused (a self-hosted platform may allow them with `HI_ALLOW_PRIVATE=1`). |
| `api` | `anthropic-messages` (the key goes in `x-api-key`), `openai-chat` or `openai-responses` (`Authorization: Bearer`), or `none` (the endpoint adds its own credential). |
| `key` | The credential. Sealed with the master key on arrival, bound to this tenant and name; `GET` never returns it. Empty only with `api: none`. |

## How a package reaches it

The package never sees the key. For each turn the platform mints a **session token** shaped like a
real key (`sk-…`), good for that turn and its provider only, and gives the package:

- `HI_PROVIDER_URL`: `http://hi-provider:8080` plus the provider's path, so a package's base-URL
  idioms hold (`https://api.deepseek.com/anthropic` becomes `http://hi-provider:8080/anthropic`);
- `HI_PROVIDER_KEY_FILE`: a file holding the token;
- the variables `provider_env` in `harness.json` names (`ANTHROPIC_API_KEY`, `OPENAI_BASE_URL`…), set
  to the token and the URL.

`hi-provider` is the sandbox's door, which forwards to the platform's **gateway**. The gateway checks
the token, swaps it for the real key, allows only the API shape's own endpoints (messages, chat
completions, responses, models; anything for `none`), forwards over TLS, counts the call and keeps
the exchange as the turn's capture. The token dies with the turn.

## Several providers, one package

Register one provider per shape you use: a package that speaks the Anthropic shape and one that
speaks OpenAI chat need two providers even for one vendor. Swap providers per request with
`harness/provider/model`; the package's `provider_env` decides which variables it reads, so a package
written for the Anthropic shape expects a provider of that shape.
