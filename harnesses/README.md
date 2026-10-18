# Harnesses

Twenty-three harnesses ship with the platform, one folder each:
- a `harness.json`;
- a `run.sh` that maps the request onto the CLI's own flags;
- a `report.py` that passes the CLI's output through and writes back what the server reads.

A few carry one more file their run script uses. They are not server code: read one, change it,
register it again, and the next request uses it. Every one runs in the built-in `default`
sandbox, which has all of their CLIs installed. Every one answers a first request and continues
the conversation on the next one with `previous_response_id`, and every one has been verified
doing both, live.

## Register them

These folders ship inside the installed package, so `hi` can register them by name:

```bash
hi harness add --builtin              # all 23
hi harness add --builtin claude-code codex
hi harness add ./harnesses/codex      # or any folder, including one you changed
```

Underneath, a harness's PUT body is its `harness.json` with every other file in its folder as a
script. The same thing with `curl` and `jq`, against a running server:

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

Any provider that serves the shape a CLI speaks works the same way: Claude Code runs on DeepSeek
by changing `"provider": "anthropic"` to `"provider": "deepseek"`.

## What ships

| Harness | Name, for `hi` | Default provider |
|---|---|---|
| [Aider](aider/) | `aider` | `anthropic` |
| [CheetahClaws](cheetahclaws/) | `cheetahclaws` | `openai` |
| [Claude Code](claude-code/) | `claude-code` | `anthropic` |
| [Cline](cline/) | `cline` | `anthropic` |
| [Codex](codex/) | `codex` | `openai` |
| [DeepSeek Harness](deepseek-harness/) | `deepseek-harness` | `deepseek` |
| [Gajae Code](gajae/) | `gajae` | `anthropic` |
| [Goose](goose/) | `goose` | `anthropic` |
| [Grok CLI](grok-cli/) | `grok-cli` | `deepseek-openai` |
| [harness-engineering](harness-engineering/) | `harness-engineering` | `anthropic` |
| [Hermes](hermes/) | `hermes` | `anthropic` |
| [J-Code](jcode/) | `jcode` | `anthropic` |
| [Kilo Code](kilo/) | `kilo` | `anthropic` |
| [Kimi Code](kimi-code/) | `kimi-code` | `deepseek` |
| [MiMo Code](mimo/) | `mimo` | `anthropic` |
| [MiniMax Code](minimax-code/) | `minimax-code` | `deepseek` |
| [nanobot](nanobot/) | `nanobot` | `anthropic` |
| [OMP](omp/) | `omp` | `anthropic` |
| [OpenCode](opencode/) | `opencode` | `anthropic` |
| [OpenHands](openhands/) | `openhands` | `anthropic` |
| [OpenSquilla](opensquilla/) | `opensquilla` | `anthropic` |
| [Pi](pi/) | `pi` | `anthropic` |
| [Qwen Code](qwen-code/) | `qwen-code` | `deepseek-openai` |

The npm and PyPI CLIs in the default image are pinned to the version each harness was written
against. Goose, Kimi, Grok and JCode come from their vendors' own install scripts, which fetch the
latest release.

## Notes worth knowing

- **Instructions reach every CLI.** Each harness writes the request's `instructions` where its
  CLI reads them, before every turn:
  - `AGENTS.md` in the workspace, for most;
  - `CLAUDE.md` for CheetahClaws, and `QWEN.md` for Qwen Code, the only names they read;
  - nanobot's own workspace under `.home`, where nanobot reads its `AGENTS.md`;
  - Aider reads no instruction file, so its run script passes `AGENTS.md` with `--read`;
  - Grok reads `AGENTS.md` only in a folder it trusts, so its harness sets `GROK_FOLDER_TRUST=0`;
  - harness-engineering and OpenHands put them ahead of the task: harness-engineering reads no
    instruction file, and OpenHands treats `AGENTS.md` as untrusted context for code style only.
- **Base URLs differ by CLI.** Claude Code, Hermes and Goose want the provider url without `/v1`;
  JCode and MiMo want it with `/v1`. Each run script handles its own case in one line.
- **The sandbox reaches only the provider.** A CLI that fetches anything else at startup, a model
  catalog or a price list, is told not to: Aider uses the price map litellm bundles, MiMo defaults
  to a model in its bundled catalog, and OMP is pointed at the egress door through `PI_PROXY`, the
  variable it reads instead of `HTTPS_PROXY`.
- **stdin carries the request JSON.** OMP appends stdin to its prompt, so its run script gives it
  an empty one.
- **pi, OMP and Cline run only on Anthropic.** pi and OMP read only `ANTHROPIC_API_KEY`, not a
  base url, until their run script writes a `models.json` entry for another endpoint. Cline's
  anthropic provider always calls `api.anthropic.com`. On another provider, the egress door
  refuses their calls.
- **JCode** keeps the model a session started with and refuses `-m` on a resumed session.
- **Cline** opens its interactive UI whenever it is asked to resume (`--id`), so its harness
  drives `cline --acp`, its Agent Client Protocol mode, through `acp.py`, and loads the saved
  session there. The answer is the text it streams after the prompt; the history a loaded session
  replays first is not counted.
- **harness-engineering** keeps its conversation in memory only. Its `report.py` keeps a
  transcript in `$HOME`, and a follow-up hands the earlier turns back as its first message, the
  way the harness hands itself a summary when its context fills.
- **nanobot** has no environment variables for its provider; its run script writes its config.
