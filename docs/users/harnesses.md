# Harness folders

A harness is a folder. The folder is where everything about a coding CLI lives: how to install it,
which configuration it runs with, which files a session starts with, how to run it, how to steer and
stop it, and what to report back. The server knows none of that. It copies the folder's files in,
runs it in a sandbox, and returns everything that comes out.

Five ship in [`harnesses/`](../../harnesses/README.md): Claude Code, Codex, pi, OpenCode and Hermes,
plus `template`, a working starting point with a stand-in CLI. The reference for every field and
variable is the [harness contract](harness-contract.md).

## What a folder holds

```
<name>/
  harness.json      what the server needs to know: provider, install hosts, interrupt tier, timeouts, …
  install.sh        installs the pinned CLI into $HI_TOOLS, once per version
  run.sh            maps HI_* onto the CLI's own settings, then runs the adapter
  adapter.py        drives the CLI: the task in, steers in, a graceful stop, the result out
  hi_adapter.py     shared plumbing, identical in every folder (copy it unchanged)
  home/             config artifacts, copied into $HOME before every response
  workspace/        work artifacts, copied into a new session's workspace
  image.Dockerfile  optional: FROM hi-base, for operating-system packages install.sh can't add
```

## Artifacts: what the folder brings, and where each kind lives

| Kind | Examples | Where it's defined | Where it lives | How long |
|---|---|---|---|---|
| **Config artifacts** | instructions (`CLAUDE.md`, `AGENTS.md`, `SOUL.md`), skills, MCP config, hooks, settings, curated memory | the folder's `home/`, in the CLI's own format; and `files` in `harness.json` for anything templated, such as the request's instructions | the session's `$HOME` (`.home/` in its workspace) | copied in before every response, so the folder always wins for what it ships |
| **Work artifacts** | the project: source, data, project-level config | the folder's `workspace/` (when a session starts) and the request's files (every response) | the session's workspace | the whole session, across responses |
| **Session state** | the CLI's transcripts, memory it writes, caches | the CLI itself | `.home/`, beside what `home/` ships | the whole session; resuming continues it |
| **Reported artifacts** | memory or other files the CLI writes under `$HOME` that you want back | `report` in `harness.json`: globs under `$HOME` | returned with each response | per response |

Each response runs in a new container, but a session's workspace and `.home/` live on the server and
are mounted back at the same path every time, so work and the CLI's own memory carry on across
responses. A new session is a clean project: it never sees another session's files.

Where the first five read their config artifacts:

| Harness | Instructions | Skills | MCP | Hooks / settings | Memory |
|---|---|---|---|---|---|
| Claude Code | `.claude/CLAUDE.md` | `.claude/skills/<name>/SKILL.md` | `.claude/mcp.json`, passed with `--mcp-config` | `.claude/settings.json` | `.claude/projects/<project>/memory/` |
| Codex | `.codex/AGENTS.md` | `.codex/skills/<name>/SKILL.md` | `[mcp_servers]` in `.codex/config.toml` | `.codex/config.toml`, `.codex/hooks.json` | its sessions under `.codex/` |
| pi | `.pi/agent/AGENTS.md` | `.pi/agent/skills/<name>/SKILL.md` | `.pi/agent/mcp.json` | `.pi/agent/extensions/` | its session files |
| OpenCode | `.config/opencode/AGENTS.md` | `.config/opencode/skills/<name>/SKILL.md` | `mcp` in `.config/opencode/opencode.json` | `.config/opencode/plugins/` | its session database |
| Hermes | `.hermes/SOUL.md` | `.hermes/skills/<category>/<name>/SKILL.md` | `mcp_servers` in `.hermes/config.yaml` | `.hermes/config.yaml` | `.hermes/memories/` |

Each shipped folder carries one harmless example of each kind it loads, named `hi-live-…` (a skill,
an MCP server, a hook). The live suite checks that each one is loaded. Replace them with your own.

## Use a shipped harness

Register the folder with the server (see [Getting started](getting-started.md#3-add-a-harness)),
add a provider it speaks, and ask for it by name:

```bash
curl -s localhost:8000/responses -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "What is 17 * 23?", "instructions": "Answer in one line."}'
```

`model` is `harness[@provider][/model]`: `claude-code`, `claude-code/claude-sonnet-4-6`,
`claude-code@deepseek/deepseek-chat`. With no provider named, the server uses the one registered for
the harness's default URL and shape.

## Configure it your way

A configuration is a folder. To run Claude Code with your skills, MCP servers and hooks, copy
`harnesses/claude-code` to a new name, change `name` in `harness.json`, put the files in `home/`
where Claude Code reads them, and register the folder. To bring the same setup to Codex or Hermes,
write the same intent in their folders' `home/`, in their formats (the table above).

- **Instructions from the request** reach the CLI through `files`:
  `"files": {".home/.claude/CLAUDE.md": "{instructions}"}`. An empty render deletes the file, so a
  response without instructions never keeps the last ones.
- **Files every session should start with** go in `workspace/`.
- **Memory you want back** goes in `report`, for example `[".claude/projects/*/memory/**"]`; each
  response returns the reported files it added, changed or deleted.
- **Secrets never go in artifacts.** The provider's key reaches a harness only through the
  [credential mechanism](security.md#keys). What an MCP server needs to run goes in `install.sh`, and
  any host it calls in `run.egress`.

## Write one

Copy the template and replace its parts:

```bash
cp -r harnesses/template harnesses/my-cli
```

1. **`harness.json`.** Name it; give its default provider and the API shapes it speaks; list the hosts
   its install may reach; choose its interrupt tier (`steered` if the CLI can take more text while it
   works, `continued` if it can be stopped and resumed, else `responded`).
2. **`install.sh`.** Install the CLI, pinned, into `$HI_TOOLS`, with executables in `$HI_TOOLS/bin`.
   It runs once per version with no secrets, reaching only `install.egress`. Install anything the CLI
   would otherwise fetch at run time here: a session can reach only its provider.
3. **`run.sh`.** Map `HI_PROVIDER_URL`, `HI_PROVIDER_KEY_FILE` and `HI_MODEL` onto the CLI's own
   settings, turn off its telemetry and update checks, then `exec python3 -u "$HI_HARNESS_DIR/adapter.py"`.
4. **`adapter.py`.** Subclass `hi_adapter.Adapter`: `start` runs the CLI with the task (resuming
   `request["resume"]` if set), `on_line` reads its output and reports the resume id, answer and usage,
   `steer` hands it more text, and `stop` asks it to stop gracefully. `hi_adapter` handles stdin,
   signals, the result file and the CLI's processes; `JsonRpc` speaks to app-server and ACP CLIs.
5. **`home/` and `workspace/`.** The config and work artifacts above.

Develop it on this machine with `HI_RUNTIME=local` (no sandbox), then prove it sandboxed with the
live suite:

```bash
uv run --extra dev python scripts/live.py harnesses/my-cli \
  --url https://api.anthropic.com --api anthropic-messages --key-file ~/anthropic.key
```

It runs the folder from the library and from the API, under the gateway and with a key file, and
checks the install cache, instructions, usage, config artifacts, resume, reported artifacts, a steer,
a stop and continue, and that the key is found nowhere it shouldn't be.

## Steering is the CLI's

A steer lands at the CLI's next safe point, usually after its current tool call. A model that does all
its work in one long command can't be steered until that command ends. Some CLIs take more text into
the running turn natively; others are stopped and given the text as the next turn. The folder's
`adapter.py` decides which, and the [survey of 23 harnesses](../../harnesses/README.md#more-harnesses)
records how each CLI can do it.
