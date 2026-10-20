# Kimi Code — kimi 2.2.0 (pin: none; vendor install at /usr/local/bin/kimi, a single 190 MB Node-SEA ELF)

**Verdict:** works. The 2.2.0 rewrite still has `-p`, `--output-format stream-json` and `-S`, and DeepSeek, Anthropic and OpenAI all answered through the `KIMI_MODEL_*` env family.
**Tier:** steered. Under `kimi web`, POST `/sessions/{id}/prompts` followed by `/prompts/{pid}:steer` stopped the counting at 3, and done.txt then held DONE.

## Inputs
- Headless: `kimi -p "<task>" --output-format stream-json` (task as an argument; stdin is not read). The default output format is `text`.
- Approvals: `-p` runs in permission mode `auto` without any flag (wire: `permission.set_mode auto`) and never asks. `--auto` = Never Ask; `-y/--yolo` = Ask When Needed. Do not use `-y`.
- Model: `-m <alias>` takes an alias from config.toml. With the env family, the alias is `__kimi_env_model__` and is already the default.
- Working dir: the process cwd. There is no `--cwd` flag. `--add-dir <dir>` adds more workspace roots.
- Instructions: `AGENTS.md`/`agents.md`/`.kimi-code/AGENTS.md` in every dir from the project root (`.git`) down to the cwd, plus `~/.kimi-code/AGENTS.md` and `~/.agents/AGENTS.md`. The model follows it ("end every reply with ZEBRA-42" was obeyed). `CLAUDE.md` is not read. `-r <id>` is a hidden alias of `-S <id>`.

## Provider
- Env family, applied when `KIMI_MODEL_NAME` is set: `KIMI_MODEL_NAME`, `KIMI_MODEL_API_KEY` (required), `KIMI_MODEL_PROVIDER_TYPE` = `kimi`|`anthropic`|`openai` (default `kimi`), `KIMI_MODEL_BASE_URL`.
  - Base URL defaults: kimi `https://api.moonshot.ai/v1`, openai `https://api.openai.com/v1`, anthropic none.
  - Optional: `KIMI_MODEL_MAX_CONTEXT_SIZE` (default 262144), `_MAX_OUTPUT_SIZE`, `_CAPABILITIES` (default `image_in,thinking`), `_THINKING_EFFORT`, `_ADAPTIVE_THINKING`, `_REASONING_KEY`, `_DISPLAY_NAME`.
  - ANTHROPIC_*/OPENAI_* are ignored.
- Shapes:
  - `anthropic` = Messages. The URL has no `/v1`: `https://api.anthropic.com` and `https://api.deepseek.com/anthropic` both tested.
  - `openai` = chat completions (the openai-legacy provider, `chat.completions.create`). The URL includes `/v1`; gpt-5-mini tested.
  - OpenAI Responses (`type = "openai_responses"`) is available only through config.toml. Not tested.
- Config alternative with no secret on disk, in `~/.kimi-code/config.toml`: `[providers.hi] type="anthropic" base_url=... api_key_env="HI_PROVIDER_KEY"`, plus `[models.hi] provider="hi" model="deepseek-chat" max_context_size=131072` and `default_model="hi"`. `kimi doctor config` passed and it ran in web mode.
- No login step. The key is never persisted: a scan of every run home found none.
- Honors `HTTPS_PROXY`: every CONNECT went through my logging proxy. I also set `NODE_EXTRA_CA_CERTS` for this machine's MITM CA.
- Startup fetches, each with the env var that stops it:
  - `code.kimi.com` and `cdn.kimi.com` (update check): `KIMI_CODE_NO_AUTO_UPDATE=1`.
  - `telemetry-logs.kimi.com`: `KIMI_DISABLE_TELEMETRY=1`.
  - With both set, only the provider host was contacted, in `-p` and in `kimi web`.

## Artifacts it loads
- `$HOME/.kimi-code/` (the dir moves with `KIMI_CODE_HOME`):
  - `config.toml`: providers, models, `default_model`, `thinking`, `[[hooks]]`, `permission.rules`, `loop_control`. Hooks are read from source only, not tested.
  - `tui.toml`, `AGENTS.md`, `mcp.json` (`{"mcpServers":{name:{command,args,env}|{url,headers}}}`), `skills/<name>/SKILL.md` (frontmatter `name`, `description`). Also `$HOME/.agents/AGENTS.md` and `$HOME/.agents/skills/`.
- From the workspace: AGENTS.md as above; `<root>/.kimi-code/skills`, `<root>/.agents/skills`; `<root>/.mcp.json`; `<cwd>/.kimi-code/mcp.json`.
- Custom slash commands: unknown.

## Outputs
- `-p --output-format stream-json` prints NDJSON in this order:
  1. `{"role":"meta","type":"system.version","version":"2.2.0"}`
  2. `{"role":"assistant","content":"..."}` or `{"role":"assistant","tool_calls":[{type:"function",id,function:{name,arguments}}]}`
  3. `{"role":"tool","tool_call_id","content"}`
  4. Last, on success only: `{"role":"meta","type":"session.resume_hint","session_id":"session_<uuid>","command":"kimi -r ..."}`
- A step's tool call and its result are printed together after the tool finishes.
- No usage, cost or error events reach stdout. Shell tool output is also echoed to stderr.
- Exit codes:
  - 0 = success.
  - 1 = failure, with `error: failed to run prompt: provider.auth_error: 401 ...` on stderr. An unknown `-S` id also exits 1 (`Session "..." not found`).
  - 130 = SIGINT.
- Usage: `usage.record` `{inputOther,output,inputCacheRead,inputCacheCreation}` per step in the session's `wire.jsonl`; the turn outcome is `turn.ended {reason: completed|cancelled|failed, error:{code,message}}`. No cost anywhere (REST session `usage` stays 0, `total_cost_usd` too).
- Resume id timing in `-p`: stdout has it only at the end, and not at all after SIGINT. It reaches `$HOME/.kimi-code/session_index.jsonl` (`{"sessionId":...}`) 1.3 s after start, before the first model reply.

## State it keeps
- All under `$HOME/.kimi-code/`:
  - Sessions: `sessions/wd_<dirname>_<hash>/<session_id>/{state.json,agents/main/wire.jsonl,logs/kimi-code.log}`. wire.jsonl is the full transcript.
  - `session_index.jsonl`, `workspaces.json`, `device_id`, `logs/kimi-code.log`, `updates/rollout.log`, `cache/query-store/`.
  - Web mode only: `server.token` and `server/instances/*.json`.
- `$HOME/.cache/kimi-code/native/2.2.0/...`: about 2 MB of native modules, extracted on the first run.
- Nothing is written into the workspace.

## Continue
`-S <id>` (or `-r <id>`) resumes a session; `-c` continues the last session for the cwd. ORCHID test: run 1 replied "OK". Run 2 with `-S` answered "ORCHID.", `-r` answered "orchid" and `-c` answered "ORCHID". A session created over REST also resumes in a new `kimi web` process that shares the same HOME (tested).

## Mid-turn steering
- `-p` mode has no stdin channel.
- `kimi acp` rejects a second `session/prompt` during a turn with `invalidRequest` `turn.agent_busy` (read in source, not tested); it has only `session/cancel`.
- `kimi web --no-open --port P` (binds 127.0.0.1) provides REST under `/api/v1`. Every request needs `Authorization: Bearer $(cat $HOME/.kimi-code/server.token)`.
  1. `POST /sessions {"metadata":{"cwd":"<ws>"}}` returns `data.id`. This is the resume id, known at once.
  2. `POST /sessions/{id}/prompts {"content":[{"type":"text","text":"..."}],"model":"__kimi_env_model__","permission_mode":"auto"}` returns `{prompt_id,status:"running"|"queued"}`.
     - **`model` is required.** Without it the turn fails with `model.not_configured`, even when config.toml sets `default_model`.
  3. Steer: POST the new text the same way. If it comes back `status:"queued"`, send `POST /sessions/{id}/prompts/{pid}:steer` with body `{}`. An empty body with a JSON content-type returns error 50001. If no turn is active, `:steer` returns 40402, but the prompt has already started as a new turn.
  4. `GET /sessions/{id}/prompts` returns `{active, queued}`. Both empty means idle.
- Wire events: `prompt.steered`, then `turn.steer {origin:{inTurn:true}}`. A WebSocket exists (`/meta` `capabilities.websocket`); not used, since tailing wire.jsonl is enough.

## Graceful stop
- REST `POST /sessions/{id}/prompts/{pid}:abort {}` returns `{aborted:true}` and stops at once (count stayed 3). The wire gets `turn.ended reason:cancelled`. Asked afterwards, the session said it was writing 1 to 30 and got through 2, with 3 cut off. Pass.
- SIGINT to the pgid in `-p` mode: exit 130 after 0.12 s, count stopped at 3, and the session was saved with `turn.ended cancelled`. Resumed with `-S`, it said "adding numbers 1–30 … 1, 2 written, 3 attempted". Pass.
- Server shutdown: `POST /api/v1/shutdown {}` exits in ~2 s; SIGINT to its pgid in ~1.5 s.

## Worst case
Not needed, because sessions resume. If they did not, `wire.jsonl` (or `kimi export <id>`, a ZIP) is the transcript to hand back.

## The folder we should ship
- harness.json:
  - provider `deepseek`; `run.interrupt: "steered"`; stdout `application/x-ndjson`; files `AGENTS.md: {instructions}`.
  - env: `HOME={workspace}/.home`, `KIMI_DISABLE_TELEMETRY=1`, `KIMI_CODE_NO_AUTO_UPDATE=1`.
  - `KIMI_CODE_HOME` is redundant, since it equals the default. Add `NODE_EXTRA_CA_CERTS` only if the sandbox proxy re-signs TLS (unknown).
- run.sh:
  - Export `KIMI_MODEL_PROVIDER_TYPE` (anthropic by default; openai if the provider URL is OpenAI-shaped), `KIMI_MODEL_BASE_URL=${HI_PROVIDER_URL%/}`, `KIMI_MODEL_API_KEY=$HI_PROVIDER_KEY`, `KIMI_MODEL_NAME=${HI_MODEL:-deepseek-chat}`.
  - Then `exec python3 adapter.py`.
- adapter.py:
  1. Start `kimi web --no-open --port <free port>` with `start_new_session`. Send its stdout to /dev/null: it prints the bearer token.
  2. Wait for `server.token` and `GET /meta` → 200, using a client with no proxy for 127.0.0.1.
  3. Session id = `$HI_RESUME`, or else a new one from `POST /sessions`. Write `resume` to `$HI_OUTPUT` at once.
  4. Submit line 1 as a prompt (model `__kimi_env_model__`, `permission_mode:"auto"`).
  5. Tail `$HOME/.kimi-code/sessions/*/<id>/agents/main/wire.jsonl` to stdout, flushed.
  6. For each later stdin line, POST it as a prompt, then `:steer` if it was queued.
  7. Finish when `/prompts` shows no active and no queued prompt, then `POST /shutdown`.
  8. On SIGINT or stdin EOF, `:abort` the active prompt, wait for `turn.ended`, then shut down.
- report.py (or inside adapter.py), all read from wire.jsonl:
  - answer = text of the last `context.append_loop_event` whose `event.type=="content.part"` and `part.type=="text"`.
  - status = `ok`/`cancelled`/`error` from the last `turn.ended.reason` (completed/cancelled/failed); `error.code` gives the message.
  - usage = sum of the `usage.record` entries. `cost_usd` = null.
  - resume = the session id, written early.
- Fallback for the `continued` tier (plain `-p`):
  - Command: `kimi -p "$HI_TASK" --output-format stream-json ${HI_RESUME:+-S "$HI_RESUME"}`.
  - Early resume: read `sessionId` from `session_index.jsonl` (a new HOME starts with an empty index; on a resume use `$HI_RESUME`).
  - Status from the exit code (0/1/130). Usage from wire.jsonl.
- artifacts:
  - Into `.kimi-code/`: `config.toml`, `mcp.json`, `AGENTS.md` (global instructions), `skills/<name>/SKILL.md`.
  - Alternatively `.agents/skills/<name>/SKILL.md`.
- Changes from today's folder:
  - It reads `HI_SESSION_ID`; the contract's variable is `HI_RESUME`.
  - report.py writes `session_id` instead of `resume`, and writes it only at the end. On SIGINT it never writes it.
  - It writes no `status` on failure (exit 1 leaves `{}`), no usage (available in wire.jsonl), and no `cost_usd: null`.
  - There is no `run.interrupt` and no steering.
  - The "Reports no usage" description is wrong.

## Evidence
- `kimi --version` printed 2.2.0. `--help` lists `-S/-c/-y/--auto/-m/-p/--output-format/--skills-dir/--agent/--add-dir/--plan` and the commands `acp`, `web`, `session`, `export`, `fork`, `provider`, `doctor`.
- Env-var names and REST routes were read from `strings` of the binary (kap-server `routes/prompts.ts`, `config/env-model.ts`, `acp-server/session.ts`).
- PONG run, no flags: CONNECTs went to code.kimi.com, api.deepseek.com, cdn.kimi.com ×3 and telemetry-logs.kimi.com ×2. With TELEMETRY only: code and cdn. With NO_AUTO_UPDATE only: telemetry. With both: api.deepseek.com only. 4–10 s per run, exit 0.
- Anthropic `claude-sonnet-4-6` returned PONG in 2.4 s; OpenAI `gpt-5-mini` returned PONG in 3.8 s. A bogus key exited 1 with a 401 on stderr.
- Steer (web, deepseek-chat):
  - 0.2 s: prompt running. 7.5 s: count.txt had 3 lines. The second prompt came back `queued`; `:steer` returned `{steered:true}`.
  - 11.5 s: idle, with count = 3 and done.txt = DONE. Still 3 after another 3 s.
- Abort (web): `:abort` at 3 lines returned `{aborted:true}`; idle at 6.9 s with count 3. A follow-up prompt answered the counting and the numbers.
- SIGINT (`-p`, `os.killpg`): exit 130 after 0.12 s, count 3. The `-S` resume answered the counting and "1, 2 written, 3 attempted".
- Id timing: `session_index.jsonl` had the entry at 1.33 s; stdout printed `resume_hint` at 7.69 s.
- Web-mode pitfalls hit: prompts without `"model"` failed (`model.not_configured`); `:steer` with an empty body failed (50001). Key scan of all run dirs: none found. Work dir 5.3 MB.
