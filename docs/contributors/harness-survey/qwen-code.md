# Qwen Code — qwen 0.25.2 (pin: @qwen-code/qwen-code@0.25.2)

**Verdict:** works with caveats. Headless, resume and steering all pass live. Caveats: stdin is added to the prompt, it phones home by default, and real api.anthropic.com needs prompt caching turned off.
**Tier:** steered. In `--input-format stream-json` mode, an `interrupt` control_request followed by a new user message stopped the count at 3 and wrote done.txt. Separately, `--acp` with `craft/drainMidTurnQueue` injected the steer mid-turn with no abort (count 3, DONE).

## Inputs
- Task: positional `qwen [query]`. `-p` still works but is deprecated. **Stdin is read and put in front of the prompt** (verified: piped `{"task":"ZEBRA…"}` showed up in the user message), so run it with `</dev/null`.
- Headless: a positional prompt runs once and exits. Approvals: `--approval-mode yolo` (or `-y`). It never asked. Set `QWEN_CODE_SUPPRESS_YOLO_WARNING=1` to drop the stderr warning.
- Model: `-m <id>`, or `OPENAI_MODEL`/`QWEN_MODEL`/`ANTHROPIC_MODEL`. Working dir: the process cwd (no flag). `--include-directories` adds more dirs.
- Useful extras: `--max-wall-time 10m`, `--max-tool-calls N` (exit 55), `--max-session-turns N` (exit 53), `--append-system-prompt`, `--session-id <uuid>`.
- Instruction files: `QWEN.md` **and** `AGENTS.md` in the workspace (both followed: the PINEAPPLE and MANGOSTEEN suffixes were obeyed), plus `~/.qwen/QWEN.md` and `.qwen/QWEN.local.md`. Rename them with `context.fileName`.

## Provider
- Shapes (`--auth-type`): `openai` (chat completions), `openai-responses`, `anthropic`, `gemini`, `vertex-ai`, `qwen-oauth`. No login step.
- OpenAI env: `OPENAI_BASE_URL` (**with** `/v1`), `OPENAI_API_KEY`, `OPENAI_MODEL`. Also flags `--openai-base-url` / `--openai-api-key`.
- Anthropic env: `ANTHROPIC_BASE_URL` (**without** `/v1`), `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`.
- It picks the shape from the env alone only when key+model vars are set. With the model given only by `-m`, it fails "No auth type is selected". With `--auth-type openai` and no model, it sends `qwen3.7-max` (DeepSeek returns 400). So pass both `--auth-type` and `-m`.
- Results:
  - DeepSeek `/v1` (openai): OK.
  - DeepSeek `/anthropic` (anthropic): OK.
  - OpenAI gpt-5-mini via `openai-responses`: OK.
  - OpenAI gpt-5-mini via `openai` chat: **400** "max_tokens not supported, use max_completion_tokens".
  - api.anthropic.com with claude-sonnet-4-6: **400** `cache_control.scope:"global"` error. It sends a global cache scope whenever the host is native Anthropic. Fix: `~/.qwen/settings.json` `{"model":{"generationConfig":{"enableCacheControl":false}}}`, after which it returns OK (no caching).
- Other hosts at startup (seen through a logging CONNECT proxy): `models.dev` (catalog, saved to `~/.qwen/model-registry.json`) and `gb4w8c3ygj-default-sea.rum.aliyuncs.com` (usage stats; called twice). Behind a provider-only proxy both are refused and the run still succeeds. Turn them off with `QWEN_CODE_MODELS_DEV=off` and `QWEN_USAGE_STATISTICS_ENABLED=0`: after that, only `api.deepseek.com` was contacted. No update check was seen.
- Honors `HTTPS_PROXY`. **The key is never persisted** (all 3 keys grepped across HOMEs and workspaces: 0 hits).

## Artifacts it loads
- Under `$HOME/.qwen` (`QWEN_HOME` overrides): `settings.json` (holds settings, `mcpServers`, `hooks`, `env`, `modelProviders`, `security.auth.selectedType`), `QWEN.md`, `.env`, `skills/<name>/SKILL.md`, `agents/*.md` (accepts Claude Code frontmatter), `commands/*.md` (`.toml` is deprecated), `rules/`, `output-styles/<name>.md`, `hooks/*.sh` (referenced from settings).
- From the workspace: `.qwen/settings.json`, `.qwen/.env` or `.env`, `.qwen/skills/`, `.qwen/agents/`, `.qwen/commands/`, `.qwen/rules/`, `QWEN.md`/`AGENTS.md`.
- `--mcp-config <json|file>` also exists. Folder trust is off by default, so workspace settings load.

## Outputs
- `-o text|json|stream-json`; `--include-partial-messages` adds `stream_event` deltas. The stream-json lines have Claude Code's shape:
  - `system/init`: first line. Carries session_id, cwd, tools, model, permission_mode, qwen_code_version.
  - `stream_event` with `event.type=goal_state`.
  - `assistant`: message.content holds text and tool_use, plus per-call usage.
  - `user`: tool_result.
  - `result`: subtype `success` or `error_during_execution`, plus `is_error`, `result`, `usage{input_tokens,output_tokens,cache_read_input_tokens,total_tokens}`, `num_turns`, `duration_ms`, and `error.message` on failure.
- **No cost field** anywhere. `result.usage` also counts background memory-extraction calls: 4 requests / 35k tokens for "say hi", versus 1 request / 11.7k with auto-memory off.
- Resume id: `session_id` on the first line, about 2–3 s after start. `--session-id <uuid>` sets it before launch (verified).
- Exit codes:
  - 0: success.
  - 1: API error, unknown `--resume` id ("No saved session found…"), or no auth type.
  - 130: SIGINT in plain mode.
  - 53 / 55: turn cap / budget exceeded (documented, not tested).

## State it keeps
- Under `$HOME/.qwen/`:
  - transcript: `projects/<cwd with / → ->/chats/<session_id>.jsonl`;
  - usage: `usage_record.jsonl` and `usage/token-usage-YYYY-MM.jsonl` (per request, with sessionId);
  - memory: `projects/<proj>/memory/MEMORY.md`, `memories/`, and `projects/-tmp/` (memory extraction cursor);
  - catalog: `model-registry.json`;
  - other: `installation_id`, `extension-store/`, `output-language.md`, `tmp/`.
- Wrote **nothing into the workspace** (8 workspaces checked).
- Auto-memory, auto-dream and auto-skill are on by default. During one run, a background extraction saved "user wants sleep 1 before each step" as a memory, which the next turn quoted. Turn them off with settings `memory.enableManagedAutoMemory/enableManagedAutoDream/enableAutoSkill=false`.

## Continue
- `--resume <session_id>` (or `-c` for the latest session in this cwd). It is scoped to the cwd plus HOME, and the session_id stays the same across turns.
- ORCHID test: run 1 "Remember the word ORCHID. Reply OK." gave "OK". Run 2 with `--resume <id>` "Which word did I ask you to remember?" gave "ORCHID." Both exited 0.
- ACP: `loadSession: true`, plus `sessionCapabilities.resume`. `session/resume {sessionId,cwd,mcpServers}` in a new process worked. ACP sessions are saved to the same `chats/` dir, so plain `--resume` also loads them.

## Mid-turn steering
- **stream-json** (`--input-format stream-json -o stream-json`): messages are Claude Code's.
  - The **first** stdin line must be `{"type":"control_request","request_id":"init","request":{"subtype":"initialize"}}`. Its control_response carries `session_id`. Without it, control requests are ignored ("Control system not enabled").
  - User turn: `{"type":"user","session_id":"","parent_tool_use_id":null,"message":{"role":"user","content":"…"}}`.
  - A user message sent mid-turn is only **queued** until the turn ends. Test sj1: it counted to 30, then did DONE. Fail.
  - Steer = `{"type":"control_request","request_id":"int1","request":{"subtype":"interrupt"}}` followed by the user message. Test sj2 passed: count 3, done.txt=DONE. The cut-short turn emits `result` with `error_during_execution` and `error.message:"Operation cancelled."`. The tool running at that moment is aborted.
- **ACP** (`qwen --acp`, JSON-RPC over stdio, protocolVersion 1): initialize → `session/new {cwd,mcpServers:[]}` → `session/prompt`.
  - After every tool result, the agent calls the **client** method `craft/drainMidTurnQueue` with params `{sessionId, todoStopGuardWatchQueuedPrompt:true}`.
  - The client answers `{"messages":["…"],"hasQueuedPrompt":false}`, or `{"items":[{content:[ContentBlock]}]}`. The text is injected into the running turn **without aborting**.
  - Test acp1 passed: count 3, DONE, stopReason end_turn.
  - Timeout is 2 s. After 3 timeouts, or after `-32601`, it stops asking. It asks only between tool calls; there is also a client→agent `craft/midTurnSendNow`, not tested.

## Graceful stop
- Plain headless, SIGINT to the process group at count 5: exit **130** after 0.07 s, no `result` line, conversation saved. The last tool_result is "[Operation Cancelled]".
  - Resumed "What were you doing before, and how far did you get?": it named the counting and "1–5 present". Pass. **But** it then carried on counting to 30 on its own.
- stream-json `interrupt`: turn ends at once with `result` `error_during_execution`, and the process stays up for the next message.
- stream-json SIGINT: dies by signal (rc -2) after 1.0 s with no result line. The chat is saved (3 tool_results).
- stream-json **stdin EOF mid-turn does NOT stop it**: it finished the turn (26 counted, killed at 60 s). The adapter must send `interrupt` first.
- ACP: `session/cancel` gives stopReason `cancelled` in 0.3 s; a follow-up prompt worked. Stdin EOF gives `cancelled` and exit 0 in 1.1 s. SIGINT gives `cancelled`, then rc -2.
- An ACP session interrupted this way and later resumed (via plain `--resume`, and via ACP `session/resume`) answered "writing 1–30 … 1, 2 done, 3 unconfirmed". Pass.

## Worst case
Not needed: resume works in every mode. As a fallback, `chats/<id>.jsonl` is a full transcript that could be handed back.

## The folder we should ship
- harness.json:
  - provider `deepseek-openai`, `run.interrupt: "steered"`, stdout `application/x-ndjson`;
  - files: `QWEN.md` (or `AGENTS.md`, both work);
  - env: `HOME={workspace}/.home`, `QWEN_CODE_SUPPRESS_YOLO_WARNING=1`, `QWEN_CODE_MODELS_DEV=off`, `QWEN_USAGE_STATISTICS_ENABLED=0`, and optional `QWEN_AUTH_TYPE=openai` to override with `anthropic` or `openai-responses`.
- run.sh:
  - Export the provider by shape: openai uses `OPENAI_BASE_URL=${url%/}` and `OPENAI_API_KEY`; anthropic uses `ANTHROPIC_BASE_URL=${url%/v1}` and `ANTHROPIC_API_KEY`. Set the shape's `*_MODEL` too.
  - Write `~/.qwen/settings.json` only if it is absent, so an artifact wins. Contents: memory auto features off, `privacy.usageStatisticsEnabled:false`, and `enableCacheControl:false` when the host is api.anthropic.com.
  - Command: `qwen --approval-mode yolo --auth-type "$t" -m "$model" ${HI_RESUME:+--resume "$HI_RESUME"}`. For steered, run it via `adapter.py`; for single-shot, use `-o stream-json "$HI_TASK" </dev/null`.
- adapter.py (prototype works: `work/qwen-code/proto/adapter.py`, count 3, DONE, exit 0):
  - Start `qwen --input-format stream-json -o stream-json …` in its own session, so the server's SIGINT reaches only the adapter.
  - Send `initialize`, then the user turn from line 1's task.
  - For each later stdin line: if busy, send `interrupt`, then send the user message.
  - On stdin EOF or SIGINT: send `interrupt` if busy, wait for the `result`, then close qwen's stdin (it exits 0).
  - Pass stdout through.
  - Alternative: drive `--acp` and answer `craft/drainMidTurnQueue` from a queue. This is true injection without killing the running tool, but its stdout is ACP JSON-RPC with no token usage (only `usage_update` context size).
- report.py:
  - Write `resume` from the first line's `session_id` **immediately**, before the turn ends.
  - On each `result`, add up `usage` across results; set `answer` from the last successful `result.result`.
  - Ignore `error_during_execution` results that came from our own interrupt.
  - status: `ok` if the last result succeeded, `stopped` if there was no result or the last was cancelled, else `fail`.
  - `cost_usd`: null (none reported).
- artifacts: `settings.json` → `.qwen/settings.json`; `QWEN.md` → `.qwen/QWEN.md`; skills → `.qwen/skills/<n>/SKILL.md`; agents → `.qwen/agents/<n>.md`; commands → `.qwen/commands/<n>.md`; hooks scripts → `.qwen/hooks/<n>.sh`; `.env` → `.qwen/.env`.
- changes from today's folder:
  - (1) Stdin is not redirected, so the request JSON leaks into the prompt: add `</dev/null`.
  - (2) It uses `HI_SESSION_ID` and writes `session_id`; the contract is `HI_RESUME` and `resume`, written early.
  - (3) No `--auth-type`/`-m`, and it only works on OpenAI-chat providers. api.anthropic.com needs `enableCacheControl:false`; OpenAI needs `openai-responses`.
  - (4) It phones models.dev and aliyuncs RUM: set the two env vars.
  - (5) Auto-memory inflates usage about 2–3×: turn it off.
  - (6) No `run.interrupt` and no `adapter.py`.
  - (7) The README says QWEN.md is "the only name": AGENTS.md is read too.
  - (8) No status when there is no result line (SIGINT).

## Evidence
- Plain runs (`-o stream-json --approval-mode yolo`, deepseek-chat): exit 0, 4–25 s. The first run took 24.8 s; once catalog and stats were off, runs took 3.7–6 s.
  - Events: system/init, stream_event(goal_state), assistant, result.
  - Logging-proxy run: models.dev, rum.aliyuncs.com ×2, api.deepseek.com.
- Provider matrix: ds-openai OK; ds-anthropic OK (auto-detected and with `--auth-type anthropic`); anthropic cache 400, OK with cache off; openai chat 400; openai-responses OK.
- ORCHID: `--resume b32d27b6…` gave "ORCHID." With `--session-id <uuid>` preset, resume gave "ORCHID." A bogus id gave exit 1.
- sj1 (stream-json, user msg only): steer sent at 3, count reached 30, then DONE; two results; exit 0. Fail.
- sj2 (stream-json, initialize + interrupt + user): steer at 9.6 s, interrupt control_response, result error_during_execution, new turn wrote DONE; count=3; exit 0. Pass.
- acp1 (`--acp`, drain returned the steer at count 3): DONE on the next model step; count=3; stopReason end_turn; exit 0 on EOF. Pass.
- acp2 (`session/cancel` at 3): cancelled in 0.3 s; re-prompt wrote DONE; count=3.
- sig1 (plain, SIGINT at 5): rc 130 in 0.07 s; resumed answer named counting and 1–5, then continued to 30.
- st1–st4: stream-json EOF finished the turn (count 26, killed); stream-json SIGINT rc -2 in 1 s; ACP EOF `cancelled`, rc 0 in 1.1 s; ACP SIGINT `cancelled`, rc -2 in 1 s. Resume after st3/st4 passed.
- proto adapter: steer at 3, interrupt+send, exit 0 in 20 s, count=3, DONE; results [error_during_execution, success].
