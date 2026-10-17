# Harnesses

Twenty-five harnesses ship with the platform, one folder each: a `harness.json`, a `run.sh` that
maps the request onto the CLI's own flags, and a `report.py` that passes the CLI's output through
and writes back what the server reads. They are not server code. Read one, change it, register it
again, and the next request uses it. Every one runs in the built-in `default` sandbox, which has
all of their CLIs installed, and every one with a key on hand has been run there, two turns each:
see Resume below.

## Register them

A harness's PUT body is its `harness.json` with every other file in its folder as a script. With
`curl` and `jq`, against a running server:

```bash
# a harness folder as the JSON its PUT takes
harness() {
  jq --argjson scripts "$(for f in "$1"/*; do [ "${f##*/}" = harness.json ] || jq -n --arg k "${f##*/}" --rawfile v "$f" '{($k): $v}'; done | jq -s add)" \
     '. + {scripts: $scripts}' "$1/harness.json"
}

for d in harnesses/*/; do d=${d%/}
  harness "$d" | curl -sX PUT "localhost:8000/harnesses/${d##*/}" -H 'content-type: application/json' -d @-
done
```

Each harness names a provider. Add providers under these names, or change `provider` in its
`harness.json`:

| Provider name | url | Serves |
|---|---|---|
| `anthropic` | `https://api.anthropic.com` | Anthropic Messages |
| `openai` | `https://api.openai.com/v1` | OpenAI Responses and chat |
| `deepseek` | `https://api.deepseek.com/anthropic` | DeepSeek models, Anthropic Messages shape |
| `deepseek-openai` | `https://api.deepseek.com/v1` | DeepSeek models, OpenAI chat shape |
| `gemini` | `https://generativelanguage.googleapis.com` | Google Gemini |
| `qoder` | `https://qoder.com` | a Qoder account token |

Any provider that serves the shape a CLI speaks works the same way: Claude Code runs on DeepSeek
by changing `"provider": "anthropic"` to `"provider": "deepseek"`.

## What ships

| Harness | Provider | Resume |
|---|---|---|
| aider | anthropic | yes |
| cheetahclaws | openai | yes |
| claude-code | anthropic | yes |
| cline | anthropic | no: Cline resumes only in an interactive terminal |
| codex | openai | yes |
| deepseek-harness | deepseek | yes |
| gajae | anthropic | yes |
| gemini | gemini | yes |
| goose | anthropic | yes |
| grok-cli | deepseek-openai | yes |
| harness-engineering | anthropic | no: it keeps no sessions |
| hermes | anthropic | yes |
| jcode | anthropic | yes |
| kilo | anthropic | yes |
| kimi-code | deepseek | yes |
| mimo | anthropic | yes |
| minimax-code | deepseek | yes |
| nanobot | anthropic | yes |
| omp | anthropic | yes |
| opencode | anthropic | yes |
| openhands | anthropic | yes |
| opensquilla | anthropic | yes |
| pi | anthropic | yes |
| qoder | qoder | yes |
| qwen-code | deepseek-openai | yes |

The npm and PyPI CLIs in the default image are pinned to the version each harness was written
against. Goose, Kimi, Grok and JCode come from their vendors' own install scripts, which fetch the
latest release.

## Notes worth knowing

- **Base URLs differ by CLI.** Claude Code, Hermes and Goose want the provider url without `/v1`;
  JCode and MiMo want it with `/v1`. Each run script handles its own case in one line.
- **The sandbox reaches only the provider.** A CLI that fetches anything else at startup, a model
  catalog or a price list, is told not to: Aider and litellm use the price map litellm bundles, MiMo defaults to a
  model in its bundled catalog, and OMP is pointed at the egress door through `PI_PROXY`, the
  variable it reads instead of `HTTPS_PROXY`.
- **stdin carries the request JSON.** OMP and Gemini CLI append stdin to their prompt, so their run
  scripts give them an empty one.
- **pi and OMP** read only `ANTHROPIC_API_KEY`, not a base url, so they run on Anthropic until
  their run script writes a `models.json` entry for another endpoint.
- **JCode** keeps the model a session started with and refuses `-m` on a resumed session.
- **nanobot** has no environment variables for its provider; its run script writes its config.
- **Gemini CLI** needs its auth type chosen in its settings and ignores `--yolo` in a folder it
  does not trust; its run script sets both.
