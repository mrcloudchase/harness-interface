# Harnesses

Twenty-six harnesses ship with the platform, one folder each: a `harness.yaml`, a `run.sh` that
maps the request onto the CLI's own flags, and a `report.py` that passes the CLI's output through
and writes back what the server reads. They are not server code. Read one, change it, apply it
again, and the next request uses it.

```bash
hi apply harnesses/* sandboxes/*           # all of them, against a running `hi serve`
hi apply harnesses/opencode                 # or one
```

Each names a provider. Add providers under these names, or edit the `provider:` line:

| Provider name | url | Serves |
|---|---|---|
| `anthropic` | `https://api.anthropic.com` | Anthropic Messages |
| `openai` | `https://api.openai.com/v1` | OpenAI Responses and chat |
| `deepseek` | `https://api.deepseek.com/anthropic` | DeepSeek models, Anthropic Messages shape |
| `deepseek-openai` | `https://api.deepseek.com/v1` | DeepSeek models, OpenAI chat shape |
| `gemini` | `https://generativelanguage.googleapis.com` | Google Gemini |
| `qoder` | `https://qoder.com` | a Qoder account token |

Any provider that serves the shape a CLI speaks works the same way: Claude Code runs on DeepSeek
by changing `provider: anthropic` to `provider: deepseek`.

## What ships

Every run below went through the server's API with the same two requests: "remember FALCON, then
what is 17 × 23", and on the same conversation, "what word did I ask you to remember?".

| Harness | Provider | Resume | Verified |
|---|---|---|---|
| aider | anthropic | yes | both turns |
| cheetahclaws | openai | yes | both turns |
| claude-code | anthropic | yes | both turns |
| cline | anthropic | no, Cline resumes only in an interactive terminal | first turn |
| codex | openai | yes | both turns |
| deepseek-harness | deepseek | yes | both turns |
| gajae | anthropic | yes | both turns |
| gemini | gemini | yes | not run: needs a Gemini key |
| goose | anthropic | yes | both turns |
| grok-cli | deepseek-openai | yes | both turns |
| harness-engineering | anthropic | no, it keeps no sessions | first turn |
| hermes | anthropic | yes | both turns |
| jcode | anthropic | yes | both turns |
| kilo | anthropic | yes | both turns |
| kimi-code | deepseek | yes | both turns |
| mimo | anthropic | yes | both turns |
| minimax-code | deepseek | yes | both turns |
| nanobot | anthropic | yes | both turns |
| omp | anthropic | yes | both turns |
| opencode | anthropic | yes | both turns |
| openhands | anthropic | yes | both turns |
| opensquilla | anthropic | yes | both turns |
| pi | anthropic | yes | both turns |
| qoder | qoder | yes | not run: needs a Qoder account token |
| qwen-code | deepseek-openai | yes | both turns |
| zeroclaw | deepseek-openai | yes | both turns, in its own `zeroclaw` sandbox |

All run in the built-in `default` sandbox, which has every CLI above installed at the version it
was tested with, except ZeroClaw, which is built from source in `sandboxes/zeroclaw.yaml`.

## Notes worth knowing

- **Base URLs differ by CLI.** Claude Code, Hermes and Goose want the provider url without `/v1`;
  JCode and MiMo want it with `/v1`. Each run script handles its own case in one line.
- **pi and OMP** read only `ANTHROPIC_API_KEY`, not a base url, so they run on Anthropic until
  their run script writes a `models.json` entry for another endpoint.
- **ZeroClaw** forgets between processes in its one-shot mode, so its harness drives
  `zeroclaw acp` over JSON-RPC with a small `driver.py` that keeps the session.
- **JCode** keeps the model a session started with and refuses `-m` on a resumed session.
- **nanobot** has no environment variables for its provider; its run script writes its config.
- **Gemini CLI** needs its auth type chosen in its settings and ignores `--yolo` in a folder it
  does not trust; its run script sets both.
