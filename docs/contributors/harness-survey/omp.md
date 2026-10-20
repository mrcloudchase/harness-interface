# OMP (oh-my-pi) — omp 18.12.0 (pin: @oh-my-pi/pi-coding-agent@18.12.0)

**Verdict:** works. Headless JSON, resume by id, steering and abort over `--mode rpc` all pass live. It needs `PI_PROXY`, and a `models.yml` for any non-Anthropic or non-catalog endpoint.
**Tier:** steered. In `--mode rpc`, `{"type":"steer"}` sent after 3 numbers backgrounded the running bash at once. Counting stopped at 9 of 30 and `done.txt` = DONE.

## Inputs
- Task: positional arg (`omp -p "<task>"`). Stdin is appended to the prompt, so give it `</dev/null` (from source and today's folder; not re-tested). RPC: `{"type":"prompt","message":...}` on stdin.
- Headless: `-p/--print`, `--mode text|json|rpc|rpc-ui` (also `omp acp`, ACP over stdio, not tested). No prompts: `--approval-mode yolo` (or `--auto-approve`/`--yolo`). The `ask` tool is interactive-only; in RPC it stays off unless `set_ask_dialog`.
- Model: `--model provider/id`. `anthropic/claude-sonnet-4-6` works. An id not in the catalog fails with `Model "anthropic/deepseek-chat" not found`, exit 1.
- Cwd: the launch cwd, or `--cwd`. If cwd == `$HOME` it switches to a temp dir unless `--allow-home` is given. This is harmless in the sandbox (HOME is `<ws>/.home`).
- Instructions: `AGENTS.md` and `CLAUDE.md`, found walking up from cwd. Followed: an AGENTS.md "end every reply with BANANA" gave `OK. ORCHID.\n\nBANANA`. Other knobs: `--append-system-prompt`, `~/.omp/agent/SYSTEM.md`, `RULES.md`.

## Provider
- Shapes: anthropic-messages, openai-responses and openai-completions, all verified live (plus many vendor-specific ones).
- Built-in `anthropic`: key from `ANTHROPIC_API_KEY` (or `--api-key`). Base URL from `ANTHROPIC_BASE_URL`, with or without `/v1` (code strips `/v1`); this only re-routes catalog Claude ids. `OPENAI_BASE_URL` does the same for the built-in openai provider (source only).
- Any endpoint or model, via `$HOME/.omp/agent/models.yml`:
  `providers: {hi: {baseUrl: <url>, apiKey: HI_PROVIDER_KEY, api: <shape>, models: [{id: <model>}]}}`, then `--model hi/<model>`.
  - `apiKey` is resolved as an env var name, so no secret reaches disk.
  - Verified: DeepSeek `/anthropic` with anthropic-messages; DeepSeek `/v1` with openai-completions; OpenAI `/v1` with openai-responses and with openai-completions; api.anthropic.com with anthropic-messages and tool use.
  - OpenAI-shape URLs want `/v1`. Cost is still computed for known ids.
- Proxy: **`HTTPS_PROXY` is not honored for Anthropic inference.** Its "cowork" `node:https` transport dials direct unless a proxy is set in `PI_PROXY` (or `PI_PROXY_<PROVIDER>`).
  - With only `HTTPS_PROXY`, my logging proxy saw zero CONNECTs, and the log says `provider proxy resolved ... source:"none"`.
  - With `PI_PROXY`, everything goes through it, catalogs included.
- Startup fetches (background, errors swallowed, cached 2h in `~/.omp/agent/models.db`): catalog.stencil.so, coding-intl.dashscope.aliyuncs.com, hyper.charm.land, api.commandcode.ai, api.kilo.ai, api.venice.ai, zenmux.ai. It also probes localhost:11434/8080/1234 (ollama, llama.cpp, lm-studio).
  - The background refresh runs unconditionally in non-interactive mode (`main.ts`); no setting turns it off.
  - Telemetry is OTLP only, and only when `OTEL_*` is set. No update check seen.
- No login step. The key was not found anywhere under HOME or the workspace (grep for each key after all runs).

## Artifacts it loads
- User level, under `$HOME/.omp/agent/` (override `PI_CODING_AGENT_DIR`; `--profile`/`OMP_PROFILE` isolates):
  - `config.yml` (settings), `models.yml`
  - `mcp.json` (also `.mcp.json`)
  - `skills/<name>/SKILL.md` (verified: listed as `skill:fruit-omp`)
  - `commands/<name>.md` (verified: `mango`)
  - `rules/`, `RULES.md`, `SYSTEM.md`, `prompts/`
  - `hooks/<type>/*.ts`, `extensions/`, `tools/`, `agents/`
- Project level, from the workspace: `.omp/` (same layout, plus `config.yml` and `mcp.json`), `.claude/settings.json`, `AGENTS.md`/`CLAUDE.md`, `.vscode/mcp.json` (it tried to read it).
- `~/.claude/skills/<name>/SKILL.md` was NOT picked up (tested).

## Outputs
- `--mode json` (NDJSON). Events: `session` (first line, ~2s: `{"type":"session","version":3,"id":"<uuid>","cwd":...}`), `advisor_cost_changed`, `agent_start`, `turn_start`, `message_start`, `message_update`, `message_end`, `tool_execution_start|update|end`, `turn_end`, `agent_end`, `auto_retry_*`, `auto_compaction_*`.
  - Assistant `message_end.message` holds `content[]`, `stopReason` (stop|toolUse|aborted|error), `errorMessage`, and `usage{input,output,cacheRead,cacheWrite,totalTokens,cost{...,total}}`.
  - **Usage is per model call; sum it over every assistant message_end.**
- `--mode rpc`: the same events, plus `ready`, `response` (`{id,command,success,data}`), `prompt_result` (`{id,status:completed|aborted|error,error?}`), `session_settled`, `queue_update`, `extension_ui_request` (setWidget), `available_commands_update`.
  - **The session id is only in the `get_state` response** (`data.sessionId`, `data.sessionFile`). It is available before the first prompt (2.3s); `ready` does not carry it.
- Exit codes:
  - 0: success, and RPC stdin EOF.
  - 1: API error (bad key gives `stopReason:"error"`, `errorMessage:"401 ..."`), unknown model, or unknown `--resume` id (`Session "..." not found.`).
  - 130: SIGINT.

## State it keeps
- `$HOME/.omp/agent/sessions/<cwd-slug>/<ts>_<uuid>.jsonl`, plus `agent.db`, `models.db` (~7MB catalog cache), `skill-descriptions.db`.
- `$HOME/.omp/logs/omp.<date>.<pid>.log` (debug; records proxy decisions), `$HOME/.omp/run/daemons/…` (token and scope files; no process outlives the run), `$HOME/.bun/install/cache`.
- Nothing is written into the workspace except what the model writes.

## Continue
- `--resume <id or id-prefix or path>` (`-c` continues the newest session; `--restore` resumes and finishes an interrupted turn, not tested). The lookup is global, so it works from another cwd.
- Proof: run 1 "Remember the word ORCHID. Reply OK." gave `OK. ORCHID.`. Run 2 with `--resume 01a1579d-…` "Which word did I ask you to remember?" gave `ORCHID.` with the same session id.
- Also passes in RPC: `omp --mode rpc --resume <id>`; `get_state` showed `messageCount 2` before the prompt, and the answer was `ORCHID`.

## Mid-turn steering
- `omp --mode rpc`, JSON lines in both directions:
  - Send `{"id":"x","type":"steer","message":"<text>"}`. Ack: `response{command:"steer",success:true}`, then `queue_update{steering:[...]}`.
  - Default `interruptMode:"immediate"`: a running bash returns at once with "Backgrounded early to handle an incoming message; the command keeps running" (job bg_1). The model then sees the steer and can cancel the job.
  - Also available: `follow_up`, `abort_and_prompt`, `set_interrupt_mode {"mode":"wait"}`.
- **Pass.** Run 1: the model ran `eval` python and the steer came after tool end; it still wrote DONE, but counted to 30. Run 2 triggered on count.txt reaching 3: steer at 52.5s, bash backgrounded at 52.5s, model cancelled bg_1. Final count 1–9, `done.txt`=DONE, `prompt_result completed` at 62.6s, exit 0.

## Graceful stop
- RPC `{"type":"abort"}` at 3 numbers: tool `isError`, `agent_end`, then `prompt_result{status:"aborted"}` within 0.1s. count.txt stayed at 3. Resumed run: "Writing numbers 1–30 to count.txt … only lines 1 and 2 made it … 28 numbers remain" (pass).
- SIGINT to the process group in `-p --mode json`: exit 130 after 0.14s, with no `agent_end`. The session file has `session_exit{reason:"sigint",pendingToolCalls}` and a `toolResult "Command aborted"`. Resumed: "1 — done, 2 — done, 3 — aborted" (pass).
- RPC with stdin EOF mid-run: exit 0 in 0.8s, tool aborted, no `prompt_result`, `session_exit reason:"dispose"`. RPC with SIGINT: exit 130 in 1.1s.

## Worst case
Not needed; sessions survive abort, SIGINT and EOF. A fallback is `omp --export <session.jsonl>` (HTML) or the jsonl itself handed back as context.

## The folder we should ship
- harness.json:
  - provider `anthropic`; `run.interrupt: "steered"`; `stdout: application/x-ndjson`; files `AGENTS.md: {instructions}`.
  - env: `HOME: {workspace}/.home`, plus `OMP_API: anthropic-messages` (the shape run.sh writes into models.yml; set openai-responses or openai-completions for other providers).
- run.sh:
  - Write `$HOME/.omp/agent/models.yml` with provider `hi`: baseUrl `$HI_PROVIDER_URL`, `apiKey: HI_PROVIDER_KEY` (the name, not the value), api `$OMP_API`, models `[{id: $HI_MODEL}]`.
  - `export PI_PROXY="$HTTPS_PROXY"`.
  - `exec python3 adapter.py`, which runs `omp --mode rpc --approval-mode yolo --model "hi/$HI_MODEL" ${HI_RESUME:+--resume "$HI_RESUME"}` in the workspace.
- adapter.py:
  - On `ready`: send `get_state`, then `prompt` with the task from line 1.
  - Each later stdin line: `steer` while streaming, or `prompt` if `prompt_result` already came.
  - On our stdin EOF or SIGINT: send `abort`, wait for `prompt_result`, then close omp's stdin.
  - On `prompt_result` with nothing queued: close omp's stdin; omp exits 0.
  - Pass every omp line through to stdout.
- report.py (or inside adapter.py):
  - `resume` = `get_state.data.sessionId`; write HI_OUTPUT the moment it arrives (~2s).
  - `answer` = text of the last assistant `message_end`.
  - `usage` = sum of usage fields over all assistant `message_end`; `cost_usd` = sum of `usage.cost.total`.
  - `status` from `prompt_result.status` (completed means ok, aborted means stopped, error means fail), else the last `stopReason`.
- artifacts: skills to `.omp/agent/skills/<n>/SKILL.md`; commands to `.omp/agent/commands/<n>.md`; MCP to `.omp/agent/mcp.json`; settings to `.omp/agent/config.yml`; rules to `.omp/agent/rules/*.md` or `.omp/agent/RULES.md`; hooks to `.omp/agent/hooks/<type>/*.ts`. Users should not ship `models.yml` (run.sh writes it), or run.sh should merge it.
- changes from today's folder:
  - Plain `-p --mode json`: no steering (should be rpc).
  - Uses `HI_SESSION_ID`/`session_id`, not `HI_RESUME`/`resume`.
  - Ignores `HI_PROVIDER_URL`. The README's "reads only ANTHROPIC_API_KEY, not a base url" is wrong (`ANTHROPIC_BASE_URL` and models.yml both work), so DeepSeek and OpenAI work via models.yml.
  - report.py takes usage and cost from the last message only (undercounts multi-call turns).
  - Marks `aborted` as fail.
  - Default model is `claude-sonnet-4-5`.
  - The PI_PROXY line is right and essential.

## Evidence
- Env: fresh HOME per run, `env -i`, `PI_PROXY` set to a local CONNECT-logging proxy, `NODE_EXTRA_CA_CERTS`, model claude-sonnet-4-6.
- json ORCHID: exit 0, `session` first line; resume gave ORCHID, exit 0, 3.8s.
- HTTPS_PROXY-only resume: proxy log empty, log shows `source:"none"`. With PI_PROXY: 9 CONNECTs (anthropic plus the 7 catalog hosts).
- models.yml `hi` provider: 4/4 shapes answered PONG, exit 0 (CONNECTs to api.deepseek.com and api.openai.com only).
- rpc steer run 2: events `ready, response(get_state), response(prompt), agent_start, … tool_execution_start(bash) → steer → queue_update, tool_execution_end(backgrounded), …, agent_end, prompt_result(completed), session_settled`. Numbers 1–9, DONE, exit 0.
- rpc abort: numbers 1–3, `prompt_result aborted`, exit 0 after stdin close; resume named the counting and "1 and 2".
- json SIGINT: numbers 1–3, exit 130 in 0.14s; resume named the counting and 1, 2 (3 aborted).
- rpc EOF: exit 0 in 0.8s. rpc SIGINT: exit 130 in 1.1s.
- Bad key: exit 1, `stopReason error`, 401 in `errorMessage`. Unknown `--resume` id: exit 1.
