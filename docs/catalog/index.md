# The catalog

Every package below ships with the platform and was run through the nine checks of `scripts/live.py` against a running platform on the provider named (DeepSeek or OpenAI): make a file and say done, recall it on the next turn, the archive holds it, a turn streams, a steer is accepted and answered, a running turn cancels, the trace records all of it, and a `store: false` request leaves nothing behind. Fork one with `PUT /v1/harnesses/<name>` and `{"catalog": "<name>"}`; its page shows the whole folder. [Demos](../demos.md) shows six of them running.

| Package | Default provider | Checks | Note |
|---|---|---|---|
| [aider](aider.md) | `deepseek-openai` | 6/9 | aider has no shell tool: a task that asks it to run a command is answered with a script to run instead, so the counting turn ends at once. A steer sent after the turn has ended is refused (there is nothing running to interrupt), so the interrupt and steer checks depend on timing; cancel and the rest work. That is aider's shape, not a platform fault. |
| [CheetahClaws](cheetahclaws.md) | `openai` | 9/9 | Headless CheetahClaws starts from an empty conversation every run (resume is a REPL command); it answers recall by looking at the workspace, not by remembering. |
| [Claude Code](claude-code.md) | `deepseek` | 9/9 |  |
| [Cline](cline.md) | `deepseek-openai` | 9/9 | Headless Cline cannot resume a session (that needs its ACP mode); it answers recall by looking at the workspace, not by remembering. |
| [Codex](codex.md) | `openai-responses` | 9/9 |  |
| [DeepSeek Harness](dsh.md) | `deepseek` | 9/9 |  |
| [goose](goose.md) | `deepseek` | 9/9 |  |
| [Grok Build](grok.md) | `deepseek-openai` | 9/9 |  |
| [Hermes Agent](hermes.md) | `deepseek` | 9/9 |  |
| [jcode](jcode.md) | `deepseek` | 9/9 |  |
| [Kilo CLI](kilo.md) | `deepseek` | 9/9 |  |
| [Kimi Code](kimi-code.md) | `deepseek` | 9/9 |  |
| [MiMo Code](mimo.md) | `deepseek` | 9/9 |  |
| [MiniMax Code](minimax-code.md) | `deepseek` | 9/9 |  |
| [nanobot](nanobot.md) | `deepseek` | 9/9 |  |
| [Oh My Pi](omp.md) | `deepseek` | 9/9 |  |
| [OpenCode](opencode.md) | `deepseek` | 9/9 |  |
| [OpenHands](openhands.md) | `openai` | 9/9 |  |
| [OpenSquilla](opensquilla.md) | `deepseek` | 8/9 | OpenSquilla prints its answer as one JSON line at the end of the turn, so a streamed response arrives as one chunk rather than many. |
| [pi](pi.md) | `deepseek` | 9/9 |  |
| [Qwen Code](qwen-code.md) | `deepseek-openai` | 9/9 |  |
| [zeroclaw](zeroclaw.md) | `deepseek-openai` | 7/9 | One-shot zeroclaw keeps no conversation between runs (resume needs its ACP server), so each turn starts fresh in the same workspace, and it prints its answer in one write at the end, so a streamed response arrives as one chunk. |

Not in the catalog, and why:

- **Gemini CLI**: speaks only Google's Gemini API; neither OpenAI nor DeepSeek serves it.
- **Qoder CLI**: runs on Qoder's cloud and needs a Qoder account; the provider is not yours to choose.
- **SystemOne**: needs a TypeSafe decision-model provider beside the coding model.
- **Agent Zero**: has no command line; the reference drives it in-process with a Python driver, which is a harness of its own.
