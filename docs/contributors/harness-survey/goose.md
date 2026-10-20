# Goose — goose 1.55.0 (pin: none; vendor install script, latest)

**Verdict:** works — headless `goose run` and `goose acp` both work behind a provider-only proxy. Anthropic, DeepSeek (both shapes) and OpenAI all answered live.
**Tier:** steered — in `goose acp`, `_goose/unstable/session/steer` stopped counting at 4 and wrote done.txt. `session/cancel` stopped it at 3. A loaded session remembered "got as far as 3".

## Inputs
- Task: `goose run -t TEXT`, or `-i FILE` (`-i -` reads stdin). With `-t`, stdin is ignored. `goose run` never prompts. In ACP the task goes in as `session/prompt`.
- Approvals: env `GOOSE_MODE=auto` (no flag). It never asked. ACP reports `currentModeId:"auto"`. Other modes: approve, smart_approve, chat.
- Model: `--provider`/`--model`, or env `GOOSE_PROVIDER`/`GOOSE_MODEL`. Working dir: the process cwd (no flag). Also `--system TEXT`, `--max-turns N`, `--no-session`, `--no-profile`, `--with-builtin`, `--with-extension`.
- Instructions: reads `AGENTS.md` and `.goosehints` in cwd, plus `~/.config/goose/.goosehints`. All three were followed (BANANA, PAPAYA, KIWI). It does **not** read `CLAUDE.md` (MANGO was not in the request log).

## Provider
- `anthropic` provider (Messages):
  - env `ANTHROPIC_HOST` **without /v1** (it appends `/v1/messages`; `/v1` gives a 404 at `.../v1/v1/messages`) and `ANTHROPIC_API_KEY`
- `openai` provider:
  - env `OPENAI_API_KEY`, plus `OPENAI_HOST` (without /v1) or `OPENAI_BASE_URL` (**with** /v1)
  - It sent the Responses shape (`input`) for gpt-5-mini and chat completions (`messages`) for deepseek-chat. How it picks the shape is unknown (probably the model name).
- Tested OK:
  - deepseek-chat through `ANTHROPIC_HOST=https://api.deepseek.com/anthropic` and through `OPENAI_HOST=https://api.deepseek.com`
  - gpt-5-mini through `OPENAI_HOST=https://api.openai.com` and through `OPENAI_BASE_URL=https://api.openai.com/v1`
- No login step. It honors `HTTPS_PROXY` (all traffic went through my logging CONNECT proxy).
- Other hosts: every run CONNECTs `models.dev:443`, a model catalog (about 5.8 MB, cached in `~/.local/share/goose/model_catalog/`).
  - When denied, runs did not fail and did not slow down. I found no switch to turn it off.
  - `cost_usd` was still reported on Anthropic, on OpenAI, and on DeepSeek over the openai shape, but not on DeepSeek over the anthropic shape.
- PostHog URL is in the binary; no telemetry connection was seen. `GOOSE_TELEMETRY_OFF` exists.
- Each run makes one extra LLM call to name the session (`GOOSE_DISABLE_SESSION_NAMING` exists; not tested).
- Key persistence: none. All three keys grepped across every HOME and log: 0 hits. Keys come from env; nothing is written unless you run `goose configure`. `llm_request.N.jsonl` logs hold full prompts, not headers.

## Artifacts it loads
- Config: `~/.config/goose/config.yaml` (`extensions:` = MCP servers, GOOSE_* settings) and `~/.config/goose/.goosehints`. `GOOSE_ADDITIONAL_CONFIG_FILES` adds more (untested).
- Skills (each `<name>/SKILL.md`), verified with `goose skills list`:
  - HOME: `~/.config/goose/skills/`, `~/.agents/skills/`, `~/.claude/skills/` (not `~/.goose/skills`)
  - workspace: `.goose/skills/`, `.agents/skills/`, `.claude/skills/`
- MCP:
  - per run: `--with-extension "CMD"`, `--with-streamable-http-extension URL`
  - in ACP: `mcpServers` in `session/new`
- Recipes: `.goose/recipes`, `.agents/recipes`, `GOOSE_RECIPE_PATH`. Plugins: `goose plugin install <git>`. Hooks: strings only. None of these tested.

## Outputs
- `--output-format text|json|stream-json`.
- stream-json starts with a 3-line text **banner on stdout**, before any LLM call. It holds `● new session|resuming · <provider> <model>` and `<SESSION_ID> · <cwd>`. `-q` hides it, and the id with it.
- Then NDJSON:
  - `{"type":"message","message":{id,role,content}}`: assistant text is **token-chunked** (many events share one `id`). Content types: `text`, `toolRequest`, `toolResponse`, `error{kind,message}`.
  - `{"type":"complete",total_tokens,input_tokens,output_tokens,cache_read_input_tokens,cache_write_input_tokens,cost_usd}`
  - `{"type":"error","error":"..."}`
- `json` prints one object `{messages, metadata:{...tokens, cost_usd, status}}` at the end.
- **`complete` usage and cost are cumulative for the session**, not the run: 4842 → 9810 → 14898 tokens over two resumes.
- Exit codes:
  - 0 = ok
  - 1 = error (401 gives an `error` event; an unknown name gives `Error: No session found with name`)
  - 1 = SIGINT (`"error":"Headless run interrupted"`, no `complete`)
- Inherited `RUST_BACKTRACE=1` adds backtraces on stderr.
- ACP (`goose acp`, JSON-RPC ndjson on stdio):
  - `session/update` kinds: `agent_message_chunk`, `user_message_chunk`, `tool_call` (title, rawInput), `tool_call_update` (status, rawOutput)
  - `usage_update{used,size,cost:{amount}}`: the cost is session-cumulative
  - `session_info_update` carries `title`, `_meta.goose.activeRunId` (run_<uuid> at start, null at end) or `_meta.goose.queuedSteer`
  - `session/prompt` result: `{stopReason:"end_turn"|"cancelled", usage}`. That usage covers the last request only.
  - With `clientCapabilities._meta.goose.customNotifications:true` it also sends `_goose/unstable/session/update` (`message_usage` per request with cost, and `accumulated*` totals).
- Session id format is `YYYYMMDD_N`, unique only within one sessions.db. Run mode prints it in the banner at t≈0; ACP returns it in the `session/new` result.

## State it keeps
- All under `$HOME`; the workspace got nothing but the task's own files.
  - `~/.local/share/goose/sessions/sessions.db` (sqlite plus -wal/-shm)
  - `~/.local/share/goose/model_catalog/`, `~/.local/share/goose/apps/`
  - `~/.local/state/goose/logs/cli/<date>/*.log` and `llm_request.N.jsonl` (full requests)
  - `~/.config/goose/`
- XDG paths, so a read-only root is fine.

## Continue
- `goose run -r --session-id 20261020_1 -t ...`: "Remember the word ORCHID. Reply OK.", then the resumed run answered "**ORCHID**". Pass.
- `-n NAME`, then `-r -n NAME`: pass. Names are not unique: a duplicate `-n` makes a new session and `-r -n` takes the newest. `-r -n missing` exits 1.
- ACP `session/load {sessionId,cwd,mcpServers:[]}` in a new process: ORCHID. Pass. It replays the history as message chunks before its result; skip those.
- Run mode and ACP share sessions: an ACP session resumed fine with `goose run -r`.

## Mid-turn steering
- Protocol on `goose acp` stdio:
  1. `initialize {protocolVersion:1,clientCapabilities:{}}`
  2. `session/new {cwd,mcpServers:[]}`
  3. `session/prompt {sessionId,prompt:[{type:"text",text}]}` (async). The run id arrives in `session_info_update._meta.goose.activeRunId`.
  4. `_goose/unstable/session/steer {sessionId, expectedRunId:<activeRunId>, prompt:[{type:"text",text}]}` returns `{runId, messageId:"steer_<uuid>"}`.
- The steer is queued (`queuedSteer`), then injected as a user message (`user_message_chunk`) at the next tool or turn boundary of the same run.
- Errors (all `-32602`):
  - empty prompt: "prompt must not be empty"
  - wrong run id: the error carries `data.actualRunId`
  - idle: "no active run to steer", so send it as a new `session/prompt` instead
- Counting test: steer at count 3 (9.5 s). It wrote 4 (a tool call already in flight), then `echo DONE > done.txt`, then end_turn at 14.9 s. done.txt = DONE. **Pass.**
- A steer during a text-only essay was applied too (ZEBRA appended in the same run).

## Graceful stop
- ACP `session/cancel {sessionId}` (notification): `stopReason:"cancelled"` in 0.3 s, count stayed at 3. The follow-up said "got as far as **3**". **Pass.**
- `goose run` plus SIGINT to the process group: exit 1 in 0.11 s, then raw text `...what would you like me to do?`, then the `error` event (no `complete`). The conversation was saved, and `-r -n cnt` named the counting task and "as far as **3**". **Pass.**
- `goose acp` plus SIGINT: dies at once (rc -2), with no cancel, and the last tool result was lost (the resumed run said "through 2"). So the adapter must run it in its own process group, catch SIGINT and send `session/cancel`. Prototype adapter: interrupted in 0.1 s; the resumed run said "as far as **3**".

## Worst case
Not needed: sessions persist in `.home`'s sessions.db. For a fallback, `goose session export --session-id ID --format json` gives the transcript, and `goose session import` exists.

## The folder we should ship
- harness.json:
  - `provider:"anthropic"`, `run.interrupt:"steered"`, `run.stdout:"application/x-ndjson"` (the ACP lines, passed through)
  - `env {HOME:"{workspace}/.home", GOOSE_MODE:"auto", RUST_BACKTRACE:"0"}`
  - `files {"AGENTS.md":"{instructions}"}`
- run.sh: put the artifacts in place, then set the provider env.
  - anthropic: `ANTHROPIC_HOST="${url%/v1}"`, `ANTHROPIC_API_KEY`
  - openai shape: `GOOSE_PROVIDER=openai`, `OPENAI_BASE_URL=<url with /v1>`, `OPENAI_API_KEY`
  - then `GOOSE_MODEL=$HI_MODEL` and `exec python3 adapter.py`
- adapter.py drives `goose acp` (prototype tested: `work/goose/proto/adapter.py`):
  - start it with `start_new_session=True`
  - `initialize`, then `session/new`, or `session/load` when HI_RESUME is set (ignore the replay)
  - write `{"resume":id}` to HI_OUTPUT at once
  - `session/prompt` HI_TASK
  - each later stdin line: steer with the latest activeRunId; if there is no active run, send it as the next prompt
  - on SIGINT, or at end of stdin mid-run: `session/cancel`, wait for `cancelled`, close goose's stdin
- report.py, or the adapter itself:
  - answer: agent text after the last `tool_call`
  - status: end_turn → ok, cancelled → interrupted, RPC error → fail
  - cost_usd: last `usage_update.cost.amount` minus its value after load
  - usage: sum of `message_usage` (customNotifications)
  - For a `goose run` fallback: id from the banner regex `(\d{8}_\d+) · `; usage is the `complete` totals minus the previous run's.
- artifacts:
  - `config.yaml` → `.config/goose/config.yaml`
  - `.goosehints` → `.config/goose/.goosehints`
  - skills → `.config/goose/skills/<n>/SKILL.md`
- changes from today's folder:
  - run.sh uses `HI_SESSION_ID`, not `HI_RESUME`.
  - report.py writes `session_id`, not `resume`, and only at the end.
  - It reports cumulative session usage and cost as per-run.
  - SIGINT is reported as "fail".
  - The default model is sonnet-4-5.
  - It has no `run.interrupt` and no openai branch.
  - stdout mixes the text banner with NDJSON.
  - Inherited `RUST_BACKTRACE` causes backtraces.

## Evidence
- `/usr/local/bin/goose --version` → 1.55.0 (ACP `agentInfo.version` agrees). The model was claude-sonnet-4-6 unless noted. Runs went through a logging CONNECT proxy that allowed only API hosts: `models.dev` was denied on every run, and PONG still came back in about 3 s with exit 0.
- Bad key: message `error{kind:authentication}`, then `error`, exit 1 in 2.9 s.
- ORCHID was answered via `-r -n`, `-r --session-id` and ACP `session/load`.
- ACP steer: activeRunId at 0.2 s, count 3 at 9.5 s, steer → `{runId,messageId}`, user_message_chunk at 11.9 s, end_turn at 14.9 s. count.txt = 1..4, done.txt = DONE. (A first attempt with a wrong runId was rejected, and it counted to 30.)
- ACP cancel at 3: cancelled in 0.3 s, "got as far as 3". `goose run` SIGINT at 3: exit 1 in 0.11 s, resume "as far as 3". `goose acp` SIGINT: rc -2, resume "through 2".
- Adapter prototype: a steer line made count 3 plus done.txt, exit 0, with early HI_OUTPUT `{"resume":"20261020_1"}`. SIGINT gave interrupted in 0.1 s. The HI_RESUME follow-up said "as far as **3**".
- `OPENAI_HOST=.../v1` and `ANTHROPIC_HOST=.../v1` gave a 404 at `/v1/v1/...` (after about 9 s of retries).
- Logs and scripts are in `work/goose/` (`acp_steer.jsonl`, `acp_cancel.jsonl`, `sigint.out`, `bin/`, `proto/`). HOMEs are deleted, and no key was found in any file.
