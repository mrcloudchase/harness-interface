# Grok CLI — grok 1.0.62 (1474f9cbdd91) (pin: none, vendor install script, latest)

**Verdict:** works with caveats: headless and ACP both run on DeepSeek, OpenAI Responses and Anthropic Messages through a `[model.*]` entry. Caveats: AGENTS.md is read only with `GROK_FOLDER_TRUST=0`. Agent mode sends side calls as `grok-4.6` unless they are pinned. An unknown resume id starts an x.ai device login.
**Tier:** steered: through `grok agent --always-approve stdio` (ACP), `_x.ai/interject {sessionId,text}` sent after 3 numbers stopped the count at 3 and wrote done.txt (also 4 and DONE through a prototype adapter). `session/cancel` and SIGINT both save the session, and a resumed run names the counting and a number.

## Inputs
- Task: `-p/--single <PROMPT>`, `--prompt-file <PATH>` or `--prompt-json <JSON>`. Headless mode never reads piped stdin into the prompt (docs). In ACP mode the task goes in `session/prompt`.
- Never ask: `--permission-mode bypassPermissions` = `--always-approve` = `--yolo` (hidden alias). Without it, a tool that needs approval is refused, stderr says `permission required: …`, and the exit code is still 0.
- Model: `-m <id>` selects a `[model.<id>]` entry (ours is `hi`). Working dir: cwd or `--cwd`. Other flags: `--max-turns N`, `--rules <TEXT>`, `--tools/--disallowed-tools`, `--no-subagents`, `--disable-web-search`, and the hidden `--no-wait-for-background`, `--no-auto-update` and `--trust`.
- Instruction files, per dir from repo root to cwd: `Agents.md, Claude.md, CLAUDE.md, CLAUDE.local.md, AGENT.md, AGENTS.md`, `.grok/rules/*.md` and `.claude/rules/*.md`. Home-level: `~/.grok/rules/*.md`, `~/.claude/CLAUDE.md`, `~/.claude/rules/`.
  **Project files load only in a trusted folder.** With AGENTS.md saying "end every reply with PINEAPPLE": with `GROK_FOLDER_TRUST=0` the reply ended `PINEAPPLE` (followed); with the var unset it was ignored. `--trust` should also work but was not tested.

## Provider
- Shapes (`api_backend`): `chat_completions` (default), `responses`, `messages`. All three tested live (HELLO plus one shell call):
  DeepSeek chat on `https://api.deepseek.com/v1` and also without `/v1`, OpenAI `gpt-5-mini` responses on `https://api.openai.com/v1`, and Anthropic `claude-sonnet-4-6` messages on `https://api.anthropic.com/v1` with `extra_headers={"anthropic-version"="2023-06-01"}`.
  Grok appends `/chat/completions`, `/responses` or `/messages` to `base_url`, so the URL takes `/v1`.
- Key: `env_key = "HI_PROVIDER_KEY"` in the model entry. That worked for all three shapes. For Anthropic, `env_http_headers` alone fails with "Not signed in"; `env_key` is needed.
  Grok resolves the key in this order: `api_key` → `env_key` → login token → `XAI_API_KEY`. No login step is needed.
- **The key is never persisted.** A grep for all three keys across every HOME and workspace found nothing.
  A 401 error echoes the key masked to its last 4 characters (`****d000`) into the stdout `error` event and stderr.
- Network: honors `HTTPS_PROXY`. Through an allowlist CONNECT proxy, a headless run and an ACP run each made CONNECTs only to `api.deepseek.com`.
  The model catalog fetch is skipped without xAI auth. Telemetry and trace upload are off by default (log: `telemetry_mode false`). Update checks are skipped on non-TTY stderr; set `GROK_DISABLE_AUTOUPDATER=1` anyway.
  **`GROK_AUTO_UPDATE` does not exist** in the binary, so today's setting is a no-op.
- **Agent mode only:** the title and summary side calls (and possibly prompt suggestions) send model `grok-4.6` to the custom `base_url`. DeepSeek answers 400, and the calls are wasted (4 errors on stderr per prompt).
  Fix: under `[models]` add `session_summary = "hi"` and `prompt_suggestion = "hi"`. With these: 0 errors. Not seen in headless `-p`.
- Unknown `--resume <uuid>`: "not found locally, restoring conversation from remote…". On open network it then waits forever on an x.ai device-code login. Behind the allowlist it exits 1 in about 2 s (`cli-chat-proxy.grok.com` and `auth.x.ai` denied).

## Artifacts it loads
All paths are under `$HOME/.grok` (or `GROK_HOME`):
- `config.toml`, which also holds `[mcp_servers.<n>]`, `[models]` and `[model.*]`.
- `skills/<name>/SKILL.md`, `commands/*.md`, `agents/`, `personas/*.toml`, `hooks/*.json` (always trusted), `rules/*.md`, `plugins/` (auto-trusted), `workflows/`, `lsp.json`.
- Claude compat, on by default: `~/.claude/skills`, `~/.claude/commands`, `~/.claude/settings.json` hooks, `~/.claude.json` MCP, `~/.claude/CLAUDE.md`, `~/.claude/rules`. `.agents/skills` is scanned too.
- `GROK_CONFIG` (inline JSON) or `GROK_CONFIG_PATH` adds an overlay of allowlisted keys.

From the workspace, only when the folder is trusted (`GROK_FOLDER_TRUST=0` lifts the gate): `.grok/skills|commands|hooks|rules|config.toml`, `.claude/…`, `.mcp.json`, `.cursor/…` and the instruction files above.

## Outputs
- `--output-format plain|json|streaming-json|streaming-messages-json`.
- streaming-json is one object per line. Seen: `available_commands` (first, at about 0.4 s), `text` (deltas in `data`), `thought`, `tool_call`, `tool_call_update`, `usage` (once per model response), `end`, `error`. Docs add `plan`, `max_turns_reached` and `auto_compact_*`.
- `end` holds `stopReason` (`end_turn|max_tokens|max_turn_requests|refusal|cancelled`), `sessionId`, `requestId`, `cwd`, `usage{input_tokens (uncached), cache_read_input_tokens, cache_creation_input_tokens, output_tokens, reasoning_tokens, total_tokens}`, `num_turns` and `modelUsage{<served model>:{…}}`.
  `total_cost_usd` and `total_cost_usd_ticks` never appeared on any provider (custom models have no price), so cost is null.
- **sessionId appears only on `end`.** SIGINT and errors emit no `end`, so pass `-s <uuid>` to know the id before the run starts.
- json: one pretty-printed object `{text, stopReason, sessionId, requestId, cwd, num_turns, usage, modelUsage}`, or `{"type":"error","message":…}`.
- Exit codes: 0 ok, 1 error (bad key: `error` event in 1.5 s, unknown session, `-s` id already in use), 130 SIGINT, 143 SIGTERM.
- ACP: `session/update` with `sessionUpdate` set to `agent_message_chunk|agent_thought_chunk|tool_call|tool_call_update|available_commands_update|session_info_update`.
  Many `_x.ai/*` notifications: `session_notification` (hundreds), `queue/changed`, `session/interjection`, `session/prompt_complete{promptId,stopReason}`, `sessions/changed`, `session/setup`, `mcp_initialized`.
  The `session/prompt` result is `{stopReason, _meta:{sessionId, usage{inputTokens,outputTokens,cachedReadTokens,…,modelUsage}}}`.

## State it keeps
- Sessions: `~/.grok/sessions/<url-encoded cwd>/<sessionId>/` holding `chat_history.jsonl`, `updates.jsonl`, `events.jsonl`, `summary.json`, `usage.json`, `system_prompt.txt`, `tool_definitions.json`, `rewind_points.jsonl` and `*.lock`.
  Also `sessions/session_search.sqlite` and `prompt_history.jsonl`.
- Elsewhere in `~/.grok`: `logs/unified.jsonl`, a copy of `docs/` (about 0.8 MB), `agent_id`, `installed-plugins/`. A full HOME is about 1.3 MB.
- **Nothing is written into the workspace** (checked in every run).
- Session ids are UUIDv7 (`01a157…`). Sessions are filed by cwd, so resume from the same workspace path.

## Continue
- `--resume <id>` (or a title), `-c/--continue` (latest in cwd), and `-s/--session-id <uuid>` (new session only; an id already in use → exit 1).
- Proved: run 1 `-s <uuid>` with "Remember the word ORCHID. Reply OK." → "OK, I've remembered the word ORCHID." Run 2 `--resume <uuid>` → "You asked me to remember the word ORCHID." `-c` also worked.
- ACP sessions and headless sessions are interchangeable. `session/load` (replays history as session/update lines) and `session/resume` (replay not checked) both worked in a new process. Headless `--resume` of an ACP session also worked.

## Mid-turn steering
- ACP over stdio: `grok agent -m hi --always-approve stdio`. Handshake: `initialize {protocolVersion:1, clientCapabilities:{}}`, then `session/new {cwd, mcpServers:[], _meta:{yoloMode:true}}`, which returns `sessionId` in 0.4 s.
- Steer: request `{"method":"_x.ai/interject","params":{"sessionId":…, "text":"…"}}` returns `{"result":{"status":"queued"}}`.
  Extension methods need the `_` prefix: plain `x.ai/interject` gives -32601. The agent echoes `_x.ai/session/interjection` and applies the text at the next safe point, after in-flight tool calls finish.
- Idle interject (no turn running): it runs as an `interject-fallback-…` prompt, which ends with `_x.ai/session/prompt_complete`, not a response. The adapter should send `session/prompt` when idle.
- Test (raw ACP): interject sent at count 3 (5.7 s) → the turn ended `end_turn` at 9.3 s, count.txt = 1,2,3, done.txt = DONE, and nothing more 3 s later. **Pass.**
- Through the prototype adapter (stdin line 2 = JSON string): count 4, done.txt DONE, exit 0, resume written at 0.5 s. **Pass.**

## Graceful stop
- ACP `session/cancel` (notification) at count 3 → the prompt returned `stopReason:"cancelled"` within 50 ms (`cancellationCategory:"MidTurnAbort"`). Count stayed 3.
  The same process then answered "I was writing the numbers 1 to 30 to count.txt … finished numbers 1 and 2". **Pass.**
- Headless `grok -p … -s <uuid>` with SIGINT to the process group at count 3 → exit 130 in 0.56 s, no `end` event, count stayed 3.
  `--resume <uuid>` → "…writing the numbers 1 to 30 into count.txt … I got through three numbers: 1, 2, and 3." **Pass.**
- `grok agent stdio`: SIGINT to its group → exit 130 in 2.2 s. stdin EOF mid-turn → exit 0 in 2.2 s. Both saved the session, and `session/load` in a new process named the counting and the numbers.

## Worst case
Not needed: sessions persist on every stop path tested. Fallback if `~/.grok/sessions` is lost: replay a transcript from `updates.jsonl` or `chat_history.jsonl` as the first prompt (harness-engineering style).

## The folder we should ship
- harness.json: provider `deepseek-openai`. Env: `HOME={workspace}/.home`, `GROK_FOLDER_TRUST=0`, `GROK_DISABLE_AUTOUPDATER=1` (drop `GROK_AUTO_UPDATE`). Optionally `GROK_MEMORY=0`.
  files `AGENTS.md: {instructions}`, stdout `application/x-ndjson`, `run.interrupt: "steered"`.
- run.sh: put artifacts in place, then write `config.toml` without the key:
  - `[models] default="hi"`, `session_summary="hi"`, `prompt_suggestion="hi"`.
  - `[model.hi] model=$HI_MODEL`, `base_url=${HI_PROVIDER_URL%/}`, `env_key="HI_PROVIDER_KEY"`, `api_backend` (default `chat_completions`; an `HI_API_BACKEND`-style knob for `responses`/`messages`; for messages add `extra_headers={"anthropic-version"="2023-06-01"}`), `context_window`.
  - Append an optional `$HOME/.grok/config.extra.toml` artifact for MCP and the like, because config.toml is rewritten every turn.
  - Then `exec python3 "$HI_HARNESS_DIR/adapter.py"`.
- adapter.py (prototype tested: `work/grok-cli/proto/adapter.py`):
  - Spawn `grok agent -m hi --always-approve stdio` with `start_new_session=True`, so the server's SIGINT reaches only the adapter.
  - Startup: `initialize`, then `session/resume {sessionId:$HI_RESUME,cwd,mcpServers:[]}` (or `session/new` with `_meta.yoloMode`). Write `resume` to HI_OUTPUT at once.
  - Run: `session/prompt` with HI_TASK. Each later stdin line → `_x.ai/interject` (or `session/prompt` when idle). SIGINT or EOF → `session/cancel`.
  - Wait for the prompt result, then close the agent's stdin. Pass every ACP line through to stdout, flushed. Answer any agent→client request.
  - Headless fallback (tier `continued`): `grok -p "$HI_TASK" -m hi --output-format streaming-json --permission-mode bypassPermissions` with `-s "$(uuidgen)"` on a first run or `--resume "$HI_RESUME"`.
- report.py / adapter output:
  - `resume` = the session id: from `session/new`, or the uuid passed to `-s`, written before the turn starts.
  - `answer` = `agent_message_chunk` text after the last `tool_call`, cleared when a prompt is sent so `session/load` replay doesn't leak in. In headless mode: `text` after the last `tool_call`.
  - `status`: `end_turn` → ok, `cancelled` → stopped, else fail. `error` event or exit ≠ 0 → fail.
  - `usage` = prompt result `_meta.usage` (ACP) or `end.usage` (headless). `cost_usd` = `total_cost_usd` when present, else null.
- artifacts: skills → `.grok/skills/<n>/SKILL.md`; hooks → `.grok/hooks/<n>.json`; rules → `.grok/rules/<n>.md`; commands → `.grok/commands/<n>.md`; agents → `.grok/agents/`; MCP → `.claude.json` (Claude format) or `.grok/config.extra.toml` (needs the run.sh append).
- changes from today's folder:
  - (1) Ship adapter.py with `run.interrupt: steered`.
  - (2) Read `HI_RESUME` (today: `HI_SESSION_ID`) and write `resume` (today: `session_id`), early. Today the id comes only from `end`, which is missing on SIGINT and errors.
  - (3) Add `-s <uuid>` on first headless runs.
  - (4) `GROK_AUTO_UPDATE` → `GROK_DISABLE_AUTOUPDATER=1`.
  - (5) Pin `session_summary` and `prompt_suggestion` to `hi`.
  - (6) Status: map `cancelled` and a missing `end` (today: status unset).
  - (7) Allow `api_backend` other than chat_completions.

## Evidence
- `grok -p "Reply with exactly: HELLO" -m hi --output-format streaming-json --permission-mode bypassPermissions` → exit 0. First (cold) run took 14.6 s, including an 8.6 s startup with a 5 s `persistence_init`; later runs 6 s. Events: available_commands, text×3, usage, end.
- Allowlist proxy (`api.deepseek.com` only): headless and ACP each made only `CONNECT api.deepseek.com:443`. A bad resume id made DENY `cli-chat-proxy.grok.com` and `auth.x.ai` ×3, then exit 1.
- AGENTS.md test: `GROK_FOLDER_TRUST=0` → `'Hi there, friend.\nPINEAPPLE'`; unset → `'Hi there, friend.'`.
- ORCHID: `-s 0e5cf5ad-…` then `--resume` and `-c`: all exit 0 and all recalled ORCHID. Reusing `-s` → "Session ID … is already in use", exit 1.
- `_x.ai/interject` probe: `{}` → missing field `sessionId`; `{sessionId}` → missing field `text`; `{sessionId,text}` → queued.
- Counting with interject at count 3 → stopped at 3, DONE. With cancel at 3 → `cancelled`, follow-up recalled it. Headless SIGINT → 130 / 0.56 s, resume recalled 1–3.
- Agent SIGINT → 130 / 2.2 s; EOF → 0 / 2.2 s; `session/load` recalled the work. Adapter: steer → count 4 plus DONE; SIGINT → status cancelled, exit 0 in 2.2 s; HI_RESUME run recalled the counting.
- Shapes: anthropic `messages` with only `env_http_headers` → exit 1 "Not signed in"; with `env_key` → HELLO. openai `responses` → HELLO (reasoning_tokens 128). DeepSeek without `/v1` → HELLO.
- Bad key → `{"type":"error","message":"…Unauthorized (401)…****d000…"}`, exit 1, 1.5 s.
