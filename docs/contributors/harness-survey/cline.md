# Cline — cline 3.0.73 (pin: cline@3.0.73)

**Verdict:** works with caveats. ACP mode (`cline --acp`) does headless runs, resume (`session/load`) and a clean cancel. Caveats: a detached hub daemon starts unless `CLINE_SESSION_BACKEND_MODE=local` is set, PostHog calls go to data.cline.bot and can't be turned off, ACP reports no usage, and a base URL only works through a hand-written providers.json.
**Tier:** steered — the adapter implements it: `session/cancel` (turn ends in 0.03 s, `stopReason:"cancelled"`), then `session/prompt` with the new text in the same session. Tested: count stopped at 3 and done.txt was written. ACP itself has no mid-turn inject: a second `session/prompt` is only queued (tested: counted to 30).

## Inputs
- Headless: `cline [--json] [-P <provider>] [-m <model>] [-c <cwd>] [-y | --auto-approve true] "<prompt>"`. Auto-approve defaults to true. Piped stdin (FIFO or file) is read to EOF and added to the prompt. **`-p` is `--plan` (plan mode), not print.** Other flags: `-t <s>` timeout, `--thinking <lvl>`, `-s` replaces the system prompt, `--retries`.
- `--id <sid>` resumes only in the TUI. `--json --id X "p"` and `--id X` with stdin both fail with "JSON output mode requires a prompt argument or piped stdin (interactive mode is unsupported)" (rc 1).
- ACP: `cline --acp --auto-approve true`. JSON-RPC over stdio. `[acp] starting…` goes to stderr. With auto-approve no `session/request_permission` was seen (0 in every log).
- Instructions: `AGENTS.md` in cwd, `.clinerules` (file or dir), `.cline/rules/`, `~/.agents/AGENTS.md`, `~/.cline/rules/`, `~/Documents/Cline/Rules`, `~/Cline/Rules`. The binary has no `CLAUDE.md` string. Followed: an AGENTS.md asking for "end with KIWI" and "one command per run_commands call" was obeyed (t8).

## Provider
- One provider per run, from a large catalog: `anthropic` (Messages), `openai-native`, `openai-compatible` (chat completions), `deepseek`, `openrouter`, `litellm`, … No login step is needed.
- **ACP key**: env `CLINE_API_KEY` + `CLINE_PROVIDER` + `CLINE_MODEL`. Without `CLINE_API_KEY`, `session/new` fails with "Authentication required". `cline auth` is not needed (tested), and the key is never written to disk.
- **Headless key**: the provider's own env var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`) with `-P/-m`. `CLINE_API_KEY` is ignored in headless mode. `-k` and `cline auth -k` **save the key** in `$HOME/.cline/data/settings/providers.json`.
- **Base URL**: `ANTHROPIC_BASE_URL` and `OPENAI_BASE_URL` are ignored (traffic still went to api.anthropic.com / api.openai.com). `cline auth -b` accepts only openai/openai-compatible and saves the key.
  - **What works in ACP**: write `providers.json` yourself as `{"version":1,"lastUsedProvider":P,"modes":{},"providers":{P:{"settings":{"provider":P,"apiKey":"placeholder","model":M,"baseUrl":URL},"updatedAt":"<ISO>","tokenSource":"manual"}}}` and pass the real key in `CLINE_API_KEY`.
  - `updatedAt` and a non-empty `apiKey` are required, or the entry is ignored.
  - Tested: anthropic with a bogus `…/v1` URL went to the bogus host, and openai-compatible with `https://api.deepseek.com/v1` answered PONG.
  - URLs with `/v1` worked. A bare host is not tested.
  - In headless mode, `-P/-m` overwrite the stored settings and drop `baseUrl`.
- openai-compatible: a model that isn't in its catalog falls back to `gpt-4o`. Fix it after `session/new` with `session/set_config_option {configId:"model", value:M}` (no validation; tested with deepseek-chat).
  - gpt-5-mini through openai-compatible fails: "reasoning_effort 'none' unsupported".
  - gpt-5-mini through `openai-native` works (headless and ACP). Whether that uses Responses or chat completions is unknown.
- `HTTPS_PROXY` is honored (tested through a chained logging CONNECT proxy with NO_PROXY unset).
- Other hosts at startup:
  - `registry.npmjs.org` (update check): off with `CLINE_NO_AUTO_UPDATE=1`.
  - `data.cline.bot` (PostHog feature flags and telemetry): no supported off switch (code skips it only when `IS_TEST=true`, not tested). When it is blocked (proxy 403) there is no delay: init+new 1.0 s, prompt 2.4 s.
  - The "cline" provider calls api.cline.bot (only if no provider is configured).

## Artifacts it loads
`~` means `$HOME`. `CLINE_DIR` overrides `~/.cline` and `CLINE_DATA_DIR` overrides `~/.cline/data`.
- Rules: listed under Instructions.
- Skills: `~/.cline/skills/`, `~/.agents/skills/`, and workspace `{.clinerules,.cline,.claude,.agents}/skills/`. The `<name>/SKILL.md` layout is assumed, not tested.
- MCP: `~/.cline/data/settings/cline_mcp_settings.json` (`CLINE_MCP_SETTINGS_PATH`). ACP `session/new.mcpServers` is stored, but the source doesn't show it being used.
- Hooks: `~/.cline/hooks/`, `~/Documents/Cline/Hooks/`, workspace `.clinerules/hooks/` and `.cline/hooks/`, or `--hooks-dir` / `CLINE_HOOKS_DIR`.
- Workflows (slash commands): `~/.cline/workflows/`, `~/Documents/Cline/Workflows/`, workspace `.clinerules/workflows/` and `.cline/workflows/`.
- Agents: `~/.cline/agents/`, workspace `.cline/agents/`. Plugins: `~/.cline/plugins/`, `~/.agents/plugins/`, workspace `.cline/plugins/`.
- Settings: `~/.cline/data/settings/{global-settings.json,providers.json}`.

## Outputs
- Headless `--json` prints NDJSON on stdout:
  - `hook_event` (agent_start, tool_result, agent_end, agent_error).
  - `agent_event`, whose `event.type` is iteration_start/iteration_end, content_start/content_end (text, tool, reasoning; text carries `accumulated`), `usage` (tokens and `cost`), `done`, or `error`.
  - A final `run_result` with `finishReason` (completed/error/aborted…), `usage`, `aggregateUsage.totalCost`, `text` and `model`.
  - Errors also go to stderr as `{"type":"error"}`.
  - **No session id in stdout**, only `taskId: conv_…`.
  - rc 0 on success, rc 1 on error (for example a bad key).
- ACP sends `session/update` with:
  - `agent_message_chunk`, `agent_thought_chunk`, `tool_call` (title, kind, rawInput), `tool_call_update` (completed/failed, rawOutput), `session_info_update`.
  - `user_message_chunk`, but only in the history that `session/load` replays.
  - The `session/prompt` result is `{stopReason: end_turn|cancelled|max_turn_requests}`. Provider errors come back as a JSON-RPC error -32603.
  - **The session id comes in the `session/new` result** (~1.1 s after start), with the format `<ms>_<5ch>_cli`.
  - **No usage in ACP.** Read it from `~/.cline/data/sessions/<sid>/<sid>.json` → `metadata.usage{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens,totalCost}` and `metadata.totalCost`. These are cumulative per session, so take the delta across a run. Per-message `metrics` are in `<sid>.messages.json`.
  - rc 0 when stdin closes.

## State it keeps
- Under `~/.cline/data/`:
  - `sessions/<sid>/{<sid>.json (manifest: status, usage), <sid>.messages.json (full transcript)}`
  - `db/sessions.db` and `db/teams.db` (sqlite + wal/shm)
  - `logs/cline.log` and `logs/hooks.jsonl`
  - `cache/feature-flags.json`
  - `settings/providers.json`: written on every headless run (provider and model; the key only with `-k`)
- `~/.cline/cli-node-extra-ca-certs.pem`.
- **Nothing is written to the workspace.**
- **Hub daemon**: in the default `auto` backend mode, any cline command (even `cline config`) spawns a detached `.cline --cline-hub-daemon --port 25463` that outlives the run. Later runs may route through it. `CLINE_SESSION_BACKEND_MODE=local` prevents this (tested: none spawned).

## Continue
ACP only. Start a new process, `initialize`, then `session/load {sessionId, cwd, mcpServers:[]}`, which replays the history as updates, then `session/prompt`. Tested: run 1 "Remember the word ORCHID. Reply OK." gave OK, and run 2 (new process, load) answered "**ORCHID**". Sessions created by headless runs also load over ACP (t11). Headless mode cannot resume.

## Mid-turn steering
- Source (core): pending prompts have `delivery: "steer" | "queue"`. Steer is consumed between iterations (`notifyPendingUserMessage` aborts the model stream). It is reachable only through hub RPC (`session.send_input`/`sendRuntimeSession {delivery:"steer"}`, `session.steer_first_pending_prompt`), the TUI (Ctrl+S, needs a TTY) and chat connectors (slack, telegram, discord, …).
- ACP `prompt()` calls `send({sessionId, prompt})` with no delivery. If a turn is already running, the interactive session **queues** it, and the second `session/prompt` returns `end_turn` immediately. It also replaces the stored AbortController, so a later `session/cancel` probably can't stop the running turn (source reading, not tested).
- Tested (t8): a 2nd `session/prompt` after 3 numbers returned at 15.5 s and counting went on to 30 (r1 ended at 149 s). The queued text then ran as a new turn with no open request, wrote done.txt, and its output arrived after r1's result. FAIL as steering.
- What works (t10): `session/cancel` after 3 numbers. r1 came back `cancelled` 0.03 s later, count stayed at 3, then `session/prompt` with the steer text wrote done.txt (count 3). A third prompt "what were you doing…" got "…got as far as **3**". PASS.

## Graceful stop
- ACP `session/cancel` (notification `{sessionId}`): the stop is immediate, the conversation stays in the session and the process stays usable (above).
- SIGINT to the ACP process group: cline has no handler. It died at once (rc −2, i.e. 130 in a shell) and sent no prompt response. The manifest stays `status:"running"`, but messages are saved. `session/load` in a new process answered "writing 1 to 30 … got as far as **3**". PASS.
- Closing ACP stdin mid-turn: exit rc 0 in 0.1 s, count stopped at 3.
- Headless SIGINT: exit in 0.4 s, rc −2, no `run_result` emitted. The manifest says `status:"cancelled"`, and the session loads over ACP and names counting and 3. PASS.

## Worst case
Not needed (resume works). If ever needed: `~/.cline/data/sessions/<sid>/<sid>.messages.json` holds the whole transcript as JSON, to pass back as context.

## The folder we should ship
- harness.json:
  - provider: anthropic (also works with openai-compatible / openai-native / deepseek by setting `CLINE_PROVIDER`).
  - env: `HOME={workspace}/.home`, `CLINE_SESSION_BACKEND_MODE=local`, `CLINE_NO_AUTO_UPDATE=1`.
  - files: `AGENTS.md: {instructions}`.
  - stdout: `application/x-ndjson`.
  - `run.interrupt: "steered"`.
- run.sh:
  - Set `CLINE_PROVIDER`, `CLINE_MODEL=$HI_MODEL` and `CLINE_API_KEY=$HI_PROVIDER_KEY` (env only).
  - If `HI_PROVIDER_URL` is set, write `~/.cline/data/settings/providers.json` as described in Provider (placeholder apiKey, baseUrl, updatedAt).
  - Run `python3 adapter.py | python3 report.py`, with stdin left open.
  - **No `cline auth`.**
- adapter.py (drives `cline --acp --auto-approve true`):
  - Line 1 = the request: `initialize`, then `session/load` if `HI_RESUME`, else `session/new`. Print the sid at once. For openai-compatible, call `session/set_config_option model`. Then `session/prompt`.
  - Each later stdin line (a JSON string): send `session/cancel`, wait for the `cancelled` result, then `session/prompt` with that text. Never send a second prompt while one is open.
  - On SIGINT or stdin EOF: `session/cancel`, wait for the result, close cline's stdin, wait for it to exit.
  - Auto-allow any `session/request_permission`.
- report.py:
  - resume = the sid from `session/new` / `session/load`; write it to HI_OUTPUT early.
  - answer = `agent_message_chunk` text after the last `tool_call` of the final prompt.
  - status = `ok` on end_turn, `stopped` on cancelled, `fail` on a JSON-RPC error.
  - usage / cost = delta of `metadata.usage` / `metadata.totalCost` in `~/.cline/data/sessions/<sid>/<sid>.json`, read after cline exits.
- artifacts: skills → `.cline/skills/<n>/SKILL.md`; MCP → `.cline/data/settings/cline_mcp_settings.json`; hooks → `.cline/hooks/`; rules → `.cline/rules/*.md` or `.agents/AGENTS.md`; workflows → `.cline/workflows/*.md`.
- Changes from today's folder:
  - (1) `cline auth anthropic -k "$HI_PROVIDER_KEY"` writes the real key into `.home/.cline/data/settings/providers.json` in the workspace. Drop it; the env vars are enough.
  - (2) Missing `CLINE_SESSION_BACKEND_MODE=local`, so a hub daemon is left behind and runs may be routed through it. Missing `CLINE_NO_AUTO_UPDATE=1`.
  - (3) `HI_PROVIDER_URL` is ignored but can be honored, and the description's "base URL settings are OpenAI-only" is wrong for ACP.
  - (4) Fallback model `claude-sonnet-4-5`; there is no openai-compatible model fix.
  - (5) acp.py closes stdin and has no SIGINT or steer handling (needs cancel then re-prompt), and it exits on the first RPC error.
  - (6) report.py takes the session id only from updates, writes no early resume, has no usage or cost, and maps `cancelled` to fail.

## Evidence
- Version: `cline --version` → 3.0.73 (installed global). `--help` was read, and source was read from strings in the Bun binary (`@cline/cli-linux-x64`).
- t1/t2: headless `--json -P anthropic -m claude-sonnet-4-6`.
  - `CLINE_API_KEY` gave rc 1 "Anthropic API key is missing".
  - `ANTHROPIC_API_KEY` gave rc 0 in 5.6 s, with $0.029 in `run_result`.
  - Proxy log: registry.npmjs.org, data.cline.bot, api.anthropic.com. A hub daemon (pid 8420) was left running.
- t4/t5: ACP with env only. ORCHID OK, then in a new process `session/load` → "ORCHID". providers.json was not created and no key was found anywhere (scanned the work dir: 0 files).
- t6: headless `--id <sid>` with an argument or with stdin gave rc 1 "JSON output mode requires a prompt…".
- t7: the count prompt without a rule was batched into one chained run_commands call, so steering can't land. t8 and later runs used an AGENTS.md "one command per call" rule.
- t8: 2nd `session/prompt` at n=3 → end_turn at 15.5 s; count reached 30; done.txt was written later as a queued turn.
- t10: `session/cancel` at n=3 → cancelled in 0.03 s, n stayed 3, re-prompt wrote done.txt, recall gave "3".
- t11: headless SIGINT at n=3 → rc −2 in 0.4 s, status cancelled; ACP load recall gave "3". t12: ACP SIGINT → rc −2 in 0.0 s; load recall gave "3". t12b: stdin EOF → rc 0 in 0.1 s, n=3.
- t9: ANTHROPIC_BASE_URL (bogus) and OPENAI_BASE_URL (deepseek) were ignored. `-P deepseek` with DEEPSEEK_API_KEY → PONG. `-P openai-native -m gpt-5-mini` → PONG.
- t14–t20: providers.json with baseUrl is ignored without apiKey and updatedAt. With both, ACP reached bogus-anthropic.example.com (6 retries over ~64 s, then "upstream dial failed") and DeepSeek PONG (after set_config_option model).
- t21: proxy allowing only api.anthropic.com (data.cline.bot → 403) → init+new 1.0 s, prompt 2.4 s, OK.
