# Gajae — gjc 0.18.12 (pin: gajae-code@0.18.12)

**Verdict:** works with caveats. Headless `-p --mode json` and resume work. Steering needs `--mode acp` plus a broker the adapter must start and stop itself, and a bare model name can resolve to the wrong provider.
**Tier:** steered. `_gjc/sdk/control` `turn.steer` sent after 3 numbers stopped the count at 3 and wrote done.txt=DONE, in 2 of 2 runs (auto broker and supervised broker).

## Inputs
- Task: positional argument (`gjc -p --mode json --model P/M "task"`). `@file` arguments attach files. `-p`/`--print` = non-interactive. No `--cwd` flag: it uses the process cwd.
- Approvals: `-p` never asks (bash/edit/write ran unprompted). ACP asks via `session/request_permission` unless `GJC_ACP_PERMISSION_MODE=always-allow` is set (values auto|prompt|always-allow; it is ignored if the same value is declared in the project `.env`).
- Model: `--model provider/id`. **A bare `claude-sonnet-4-6` fuzzy-matched `google-antigravity/claude-sonnet-4-6`** (exit 1, "No API key for google-antigravity/…"). Always prefix `anthropic/`.
- Instructions: reads workspace `AGENTS.md`, workspace `CLAUDE.md` and user `$HOME/.gjc/agent/AGENTS.md`. The model followed all three (tokens echoed). Also `--append-system-prompt <text|file>` (not tested).
- Also reads the workspace `.env` into its environment (documented; provider credentials are excluded from it).

## Provider
- Speaks Anthropic Messages (`anthropic`), OpenAI Responses (`openai`) and Chat Completions (custom provider in `~/.gjc/agent/models.yml` with `api: openai-completions`, `baseUrl`, `apiKeyEnv`), plus many built-ins (`deepseek`, …).
- Anthropic: `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL`. A trailing `/v1` is stripped, so both forms work (both tested). OpenAI: `OPENAI_API_KEY` + `OPENAI_BASE_URL`, which must include `/v1` because it calls `<base>/responses`. `openai/gpt-5-mini` tested OK. The generic override is `<PROVIDER_ID>_BASE_URL`.
- No login step. Honors `HTTPS_PROXY` (all traffic went through a logging CONNECT proxy with NO_PROXY unset).
- Startup fetches beyond the provider: `models.dev` and `api.deepseek.com` (model catalogs, every run, no switch found), and `raw.githubusercontent.com` (signed preset registry; `GJC_MODEL_PRESET_REGISTRY_DISABLED=1`). It also probes loopback model servers (ollama/omlx/lmstudio). Telemetry is off by default (`GJC_DISABLE_TELEMETRY=1` forces it off). Behind a proxy that refuses every host except api.anthropic.com, runs still took 4-5 s and exited 0.
- If the provider can't be reached, it retries for over 100 s and **prints nothing at all** (not even `session`). Rely on timeout_s.
- Key persistence: none. All homes, workspaces and outputs were scanned for both keys: 0 hits. The ACP broker and session-host processes hold the key in their env only.

## Artifacts it loads
- User scope `$HOME/.gjc/agent/` (override `GJC_CODING_AGENT_DIR`): `AGENTS.md`, `skills/<n>/SKILL.md` (needs frontmatter `description`; tested, the skill was used), `mcp.json`, `hooks/pre|post/<file>`, `config.yml` (settings), `models.yml` (custom providers).
- Project scope `<ws>/.gjc/…` (same layout) plus root `AGENTS.md`/`CLAUDE.md`. `.claude/skills`, `.mcp.json` and `~/.claude*` are import sources only and are NOT loaded.
- `--mcp-config <abs path>` works in `-p` mode only (unsupported in ACP, where MCP servers come from `session/new.mcpServers`). `--no-mcp` and `--no-rules` exist.

## Outputs
- `--mode json`: NDJSON. Line 1 is `{"type":"session","id":…}`, at about 2.4-3.7 s, before any model call. Then `agent_start`, `turn_start`, `message_start`/`message_update` (`assistantMessageEvent.type` text_delta/toolcall_end/…)/`message_end`, `tool_execution_start`/`…end`, `turn_end` (`message.content`, `usage{input,output,cacheRead,cacheWrite,cost.total}`, `stopReason` stop|toolUse|error|aborted, `errorMessage`/`errorStatus`), `agent_end`. There are several `turn_end`s per run, so take the last one that has text.
- Exit codes: 0 ok; 1 on a model/auth error (`stopReason:"error"`, `errorStatus:401`); **0 on SIGINT** (no `agent_end`), so status must come from events.
- ACP (`--mode acp`, NDJSON JSON-RPC on stdio): `session/update` kinds agent_message_chunk, agent_thought_chunk, tool_call, tool_call_update, user_message_chunk, session_info_update, available_commands_update. **No usage/cost events.** `session/prompt` resolves `{stopReason: end_turn|cancelled}`. Usage and cost are in the session JSONL (below).

## State it keeps
- `$HOME/.gjc/agent/sessions/v2-<scope>/<ts>_<sid>.jsonl`: the transcript, with usage and cost per assistant message. Also `agent.db`, `models.db`, `logs/gjc.<date>.log`, `machine-identity.secret`, and `sdk/` (broker.json with a loopback ws URL and token, ledger).
- **Writes into the workspace:** `<ws>/.gjc/_session-<sid>/{runtime,token-logs}/…`, fixed in code (`gjc-runtime/session-layout.ts`). Exclude or delete it after the run.
- Bun's transpiler cache goes to `$HOME/.bun/install/cache` (~29 MB). `BUN_RUNTIME_TRANSPILER_CACHE_PATH=0` removes it at no measurable startup cost.
- ACP with `--model` also writes `modelRoles.default` into `$HOME/.gjc/agent/config.yml`.

## Continue
- `-r <sessionId>` (prefix or path) resumes and appends to the same file and id; `-c` continues the latest. Tested: run 1 "Remember the word ORCHID. Reply OK." → run 2 `-r <id>` "Which word…?" → "ORCHID".
- In ACP: `session/resume {sessionId,cwd,mcpServers:[]}` in a new process after the broker was killed answered correctly ("3"). `session/load` is also advertised (not tested). Sessions are shared between modes: `-p -r <acp sid>` recalled the ACP task.

## Mid-turn steering
- `-p` mode reads no stdin. A second ACP `session/prompt` during a turn is rejected (`-32603 … "ACP session already has an active prompt"`, `data.code:"conflict"`).
- Works: `{"jsonrpc":"2.0","id":N,"method":"_gjc/sdk/control","params":{"sessionId":SID,"operation":"turn.steer","input":{"text":"…"}}}` → `{"commandId","turnId","accepted":true}`. It is consumed at the next tool boundary: the running `echo 3` finished, then the model wrote done.txt and the prompt ended `end_turn`. Result: count 3, done.txt=DONE, both runs. An optional `input.clientRef` makes it idempotent (`turn.steer_status` query; not tested).
- A steer while idle also returns `accepted:true`, but no reply was seen in 8 s. Send idle text as `session/prompt` instead.
- **Broker:** `gjc --mode acp` is a thin front end. By default it auto-spawns a `setsid`'d `sdk broker-internal` (ws://127.0.0.1:port) plus a `session-host-internal` (the real agent) and a stderr-drain. These survive the front end and SIGINT to its process group. **After SIGINT to the front end's group, the agent kept counting (3→16).** Fix (tested): run `gjc sdk broker run --agent-dir $HOME/.gjc/agent` as a foreground child and give `gjc --mode acp` the env `GJC_SDK_BROKER_AUTOSTART=0`. At the end, `session/close` removes the host; SIGTERM to the broker then exits 143 in 0.2 s, leaving nothing behind. In the container this needs loopback only (no proxy involved).

## Graceful stop
- ACP `session/cancel {sessionId}` (notification): `session/prompt` → `{"stopReason":"cancelled"}` 1.5 s later (after the running tool call). The count stayed at 3, and a follow-up in the same session answered "writing 1–30 … got through 3". `_meta.gjc.abortScope:"owned"` (or env `GJC_ACP_ABORT_SCOPE=owned`) also stops background jobs and subagents.
- `-p` mode, SIGINT to the process group: exits in 0.4 s, code 0, no `agent_end`. The transcript is saved up to the open tool call. Resuming with `-r` and asking "what were you doing…" → "writing 1–30 to count.txt … got through 3". **Pass.**

## Worst case
Not needed: resume works by id in both modes. As a fallback, the transcript JSONL above is self-contained and could be handed back as context.

## The folder we should ship
- harness.json: provider `anthropic`. `run.interrupt: "steered"`. stdout `application/x-ndjson`. env: `HOME={workspace}/.home`, `GJC_NO_TMUX=1`, `GJC_NOTIFY=off`, `GJC_NO_TITLE=1`, `GJC_MODEL_PRESET_REGISTRY_DISABLED=1`, `GJC_DISABLE_TELEMETRY=1`, `GJC_ACP_PERMISSION_MODE=always-allow`, `GJC_SDK_BROKER_AUTOSTART=0`, `BUN_RUNTIME_TRANSPILER_CACHE_PATH=0`. Put `{instructions}` in `.home/.gjc/agent/AGENTS.md` rather than the workspace root, if `files` can target HOME.
- run.sh: export `ANTHROPIC_BASE_URL="${HI_PROVIDER_URL%/}"` and `ANTHROPIC_API_KEY=$HI_PROVIDER_KEY`; set model `m=$HI_MODEL`, and if it has no `/`, use `m=anthropic/$m`. Then `exec python3 adapter.py`. adapter.py:
  1. Start `gjc sdk broker run --agent-dir $HOME/.gjc/agent` (own process group), then start `gjc --mode acp --model $m`.
  2. Send `initialize {protocolVersion:1, clientCapabilities:{}}`. Then send `session/resume` (if `HI_RESUME`) or `session/new {cwd:$HI_WORKSPACE, mcpServers:[]}`. Write the resume id at once.
  3. Send `session/prompt` (line 1 task). Stream updates to stdout.
  4. Each later stdin line: if a prompt is pending, send `_gjc/sdk/control turn.steer`; else send a new `session/prompt`.
  5. On SIGINT or stdin EOF, send `session/cancel` and wait for the prompt to settle, up to about 10 s.
  6. Shut down in this order: `session/close`, close stdin, SIGTERM the broker group, `rm -rf $HI_WORKSPACE/.gjc/_session-*`.

  Headless fallback (`continued`): `gjc -p --mode json --model $m ${HI_RESUME:+-r $HI_RESUME} "$HI_TASK"`.
- report.py: pass lines through, flushed. Resume = ACP `sessionId` (or the json `session.id`, line 1); write `HI_OUTPUT` as soon as it is known. Answer = agent_message_chunk text since the last prompt (or the last `turn_end` with text). Status: `end_turn`→ok, `cancelled`→interrupted, JSON-RPC error→fail. In `-p` mode, status comes from the last `stopReason`, not the exit code. Usage/cost = sum of `message.usage`/`usage.cost.total` over assistant entries in `$HOME/.gjc/agent/sessions/*/*_<sid>.jsonl`.
- artifacts: skills → `.gjc/agent/skills/<n>/SKILL.md`; MCP → `.gjc/agent/mcp.json`; hooks → `.gjc/agent/hooks/pre|post/<file>`; settings → `.gjc/agent/config.yml`; custom/OpenAI-compatible providers → `.gjc/agent/models.yml`; global instructions → `.gjc/agent/AGENTS.md`.
- changes from today's folder: run.sh reads `HI_SESSION_ID` (contract: `HI_RESUME`); report.py writes `session_id` (contract: `resume`) and only at EOF (it must write early). The default `claude-sonnet-5-5` and bare names are fuzzy-matched (the anthropic/ prefix is missing). There is no interrupt tier or adapter. A SIGINT'd run is reported `ok` (exit 0, last stopReason toolUse). The `artifacts` example points at `.claude/skills`, which gjc doesn't load. `.gjc/_session-*` workspace residue is not handled.

## Evidence
- Model `anthropic/claude-sonnet-4-6` throughout; proxy-logged CONNECTs.
- `--model claude-sonnet-4-6` → exit 1 google-antigravity error. `-p --mode json "Reply HELLO"` → exit 0; `session` at 3.7 s, total 7.8 s (cold first run 32.6 s).
- Bad key → exit 1, turn_end stopReason error/401. Bogus `ANTHROPIC_BASE_URL` → >100 s of retries, 0 stdout lines (killed). `/v1` and no-`/v1` base → OK.
- ORCHID resume → "ORCHID". AGENTS.md / CLAUDE.md / user AGENTS.md / user skill: all followed. `openai/gpt-5-mini` with OPENAI_API_KEY → OK (openai-responses) in 11.9 s.
- `-p` count + SIGINT(pgrp) at 3 → exit 0 in 0.4 s; count 3; resumed answer named the counting and 3.
- ACP auto-broker: session/new 5-10 s (46 s once under load). steer at 3 → accepted; end_turn at +6 s; count 3, DONE.
- ACP `session/cancel` at 3 → `cancelled` in 1.5 s; count 3; follow-up "got through 3".
- ACP second `session/prompt` mid-turn → conflict error; count reached 30.
- SIGINT to the ACP front end's pgrp → front end exit 0 in 0.1 s; host kept counting to 16+ (leftovers killed by hand).
- Supervised broker (`sdk broker run` + `GJC_SDK_BROKER_AUTOSTART=0`): cancel → `cancelled` at +0.3 s; steer → count 3, DONE; `session/close` `{}`; broker SIGTERM → 143 in 0.2 s, no processes left.
- `session/resume` in a new process after killing the broker → correct recall (9-25 s to resume).
