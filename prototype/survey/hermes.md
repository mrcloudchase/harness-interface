# Hermes Agent — hermes 0.19.0 (pin: hermes-agent[anthropic]==0.19.0)

**Verdict:** works with caveats. Headless `chat -q` resumes and stops cleanly. `hermes acp` steers mid-turn, but it needs the `[acp]` extra, which the image does not have, and `session/cancel` returns a JSON-RPC error.
**Tier:** steered. Over ACP, `session/prompt` "/steer Stop counting…" sent after 3 numbers gave done.txt=DONE and the count stopped at 3. Fallback tier: continued (SIGINT exits 130 in 2 s with the session saved, and the resumed run named "number 4 / 3 confirmed").

## Inputs
- Headless: `hermes chat -q "$TASK" -Q --yolo --provider anthropic -m MODEL [--resume ID] [--no-restore-cwd]`. The task is an argument and stdin is ignored (tested). `-Q` prints only the answer plus a session line. `--yolo` (or `HERMES_YOLO_MODE=1`) skips dangerous-command approvals, and `--accept-hooks` (or `HERMES_ACCEPT_HOOKS=1`) skips hook consent. `--max-turns N` defaults to 90.
- `hermes -z PROMPT --usage-file F` is a separate oneshot mode with a JSON usage file, but it cannot resume. With `--provider` it also needs `-m`.
- There is no cwd flag; it uses the process cwd. `--resume` cds into the session's *recorded* cwd ("↪ restored workspace dir: …" printed on stdout) unless you pass `--no-restore-cwd`.
- Instructions: it loads only one project file, the first found of `.hermes.md`/`HERMES.md` (walks up to the git root), then `AGENTS.md`, `CLAUDE.md` and `.cursorrules`/`.cursor/rules/*.mdc` (cwd only). `$HERMES_HOME/SOUL.md` (persona, auto-created) always loads. The model followed AGENTS.md ("end with BANANA") in both chat -q and ACP.
- ACP: `hermes acp --accept-hooks` speaks JSON-RPC over stdio. It has no model flags: the model comes from `config.yaml` `model.default`/`model.provider`, or from env `HERMES_INFERENCE_PROVIDER=anthropic` plus `session/set_model {modelId:"anthropic:claude-sonnet-4-6"}` (both tested).

## Provider
- It speaks Anthropic Messages (`--provider anthropic`), with the key from `ANTHROPIC_API_KEY` and the base from `ANTHROPIC_BASE_URL`. It strips a trailing `/v1` itself, so either form works. It also has OpenAI-chat providers: `openai-api` (`OPENAI_API_KEY`, `OPENAI_BASE_URL`), `deepseek` (`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`) and others (not tested).
- Swapping works: `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` plus the DeepSeek key and `-m deepseek-chat` answered PONG. A bogus base URL was used in both chat -q and ACP: all calls went to that host.
- No login step. It honors `HTTPS_PROXY` (every call went through my logging CONNECT proxy).
- Key precedence: `ANTHROPIC_TOKEN` > `CLAUDE_CODE_OAUTH_TOKEN` > `~/.claude/.credentials.json` > the auth.json pool > `ANTHROPIC_API_KEY`. Do not let the first three leak in.
- Key persistence: none in clear. `$HERMES_HOME/auth.json` gets a credential-pool entry with `source: env:ANTHROPIC_API_KEY` and a sha256 fingerprint only. I grepped every home and workspace for the key: no hits.
- Other hosts it contacts:
  - pypi.org: an update check, cached 6 h in `$HERMES_HOME/.update_check`, with no off switch.
  - github.com and release-assets.githubusercontent.com: it downloads the **tirith** scanner (38 MB) into `$HERMES_HOME/bin/`. `TIRITH_ENABLED=0` or config `security.tirith_enabled: false` stops this (tested).
  - ACP only: models.dev, openrouter.ai and api.anthropic.com for model catalogs (cached in `models_dev_cache.json` and `cache/openrouter_model_metadata.json`), with no off switch.
  - All of these fail soft. How fast they fail behind the sandbox door is not tested.
- The auxiliary client tries openrouter/nous and marks them unhealthy (log only).

## Artifacts it loads
All under `HERMES_HOME`, which defaults to `~/.hermes`:
- `config.yaml`: model, providers, `mcp_servers:`, shell `hooks:` (consent is stored in `shell-hooks-allowlist.json`), `security:`, `skills.external_dirs`, `quick_commands`.
- `.env`: secrets, which it loads.
- `SOUL.md`
- `skills/<cat>/<name>/SKILL.md`
- `memories/` (MEMORY.md, USER.md)
- `plugins/`
- `hooks/`

From the workspace it reads only the instruction file above. Workspace skills and plugins: not checked.

## Outputs
- chat -q -Q:
  - stdout: the answer text. Before it can come a "⚠ tirith … not available" line (even with TIRITH_ENABLED=0, unless config.yaml disables it) and a "↪ restored workspace dir" line.
  - stderr: "↻ Resumed session X (…)" and, **at exit only**, `session_id: <YYYYMMDD_HHMMSS_hex>`. The id can change mid-run after context compression, so trust the last line.
  - No usage, cost or JSON output. Usage and cost are cumulative per session in `$HERMES_HOME/state.db` table `sessions` (`input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, estimated_cost_usd, api_call_count, model`).
  - Exit codes: 0 ok; 1 provider failure ("API call failed after 3 retries: Connection error." on **stdout**); 130 on SIGINT.
- ACP (stdout is protocol only; INFO logs go to stderr):
  - `session/new` returns `sessionId` (a UUID) at about 3 s, before any model call. That is the early resume handle.
  - `session/update` kinds: `agent_message_chunk`, `tool_call`, `tool_call_update`, `plan`, `usage_update` (context size only), `available_commands_update`, `session_info_update`, `user_message_chunk` (replay).
  - The `session/prompt` result is `{stopReason:"end_turn", usage:{inputTokens, outputTokens, cachedReadTokens, thoughtTokens, totalTokens}}`, with no cost; cost comes from state.db (`sessions.id` = the ACP sessionId).
  - Provider failure still returns `end_turn`, with the error as message text and no `usage` field.
  - Agent→client request: `session/request_permission` (edits in the default mode). Answer `{outcome:{outcome:"selected",optionId:"allow_once"}}`, or call `session/set_mode` `dont_ask`.

## State it keeps
- Everything lives under `HERMES_HOME`:
  - `state.db` (SQLite with WAL): sessions, messages and FTS; both cli and acp sessions go here.
  - `logs/agent.log`, `logs/errors.log`
  - `auth.json`, `.update_check`, `.skills_prompt_snapshot.json`, `SOUL.md`
  - empty dirs `sessions`, `cron`, `pairing`, `image_cache`, `audio_cache`, `sandboxes`
- Nothing is written into the workspace beyond the task's own files (checked with `ls -A`).
- A background "Review the conversation…" fork runs extra model calls after turns with ≥10 tool iterations or user turns, and writes skills and memories into HERMES_HOME. Per source, `skills.creation_nudge_interval: 0` and `memory.nudge_interval: 0` turn it off (not tested).

## Continue
- `--resume <session_id>`: run 1 "Remember the word ORCHID. Reply OK." returned `OK`; run 2 with `--resume 20261020_044203_bc806a` answered `ORCHID`, with the same id.
- `-c` (no name) resumes the most recent session in this HERMES_HOME. It picked the latest session from another cwd and cd'd there, so pass the id plus `--no-restore-cwd`.
- ACP: `session/load {sessionId, cwd, mcpServers:[]}` in a **new process** replays the history as updates, then continues (tested; the answer named the count and 3).

## Mid-turn steering
- Protocol (ACP, agent-client-protocol 0.9.0, protocolVersion 1):
  1. `initialize {protocolVersion:1, clientCapabilities:{fs:{readTextFile:false,writeTextFile:false}, terminal:false}}`
  2. `session/new {cwd, mcpServers:[]}`
  3. `session/prompt {sessionId, prompt:[{type:"text", text}]}`
  4. While that request is still open, send another `session/prompt` with text `"/steer <TEXT>"`. It returns `end_turn` at once and emits the chunk "⏩ Steer queued for the active turn: <preview>". `AIAgent.steer()` appends the text to the last tool result before the next model call.
- On an idle session, `/steer TEXT` runs as a normal prompt.
- A plain (non-slash) prompt during a turn is queued and runs after it.
- Caveat (from source): a steer that lands before the turn's first tool call, or just before a final no-tool answer, stays pending on the agent and lands in a later turn.
- Test: steer sent at 36.1 s (count.txt = 3 lines). `echo DONE > done.txt` ran at 40.1 s, the turn ended at 51.6 s, count.txt stayed at 3 lines and done.txt = "DONE". **PASS.**

## Graceful stop
- chat -q with SIGINT to the process group after 4 numbers: exit 130 after 2.1 s, it printed `session_id:`, and the count stayed at 4. The resumed run answered "writing 1 to 30 … got through number 4 (3 last confirmed)". **PASS.**
- ACP `session/cancel {sessionId}` after 3 numbers: the turn stopped in 1.6 s and the count stayed at 3. But the prompt answered with a **JSON-RPC error** `-32603 "'NoneType' object has no attribute 'startswith'"` instead of `stopReason:"cancelled"`. This is a bug in `acp_adapter/server.py` ~L1606: `final_response` is None on interrupt. The session is saved; loading it later gave the right answer.
- ACP with SIGINT to the group: **does not stop**. Updates stop, but the agent kept counting to 30 and exited 0 after 87 s with no prompt response. So the adapter must shield `hermes acp` (`start_new_session=True`) and send `session/cancel` itself.
- Closing stdin when idle: exit 0 in under 1 s.

## Worst case
Not needed: both chat -q (`--resume`) and ACP (`session/load`) restore the full conversation from `state.db`. If needed, `hermes sessions export` exists (not tested).

## The folder we should ship
- harness.json:
  - provider `anthropic`; `run.interrupt: "steered"`; stdout `application/x-ndjson`; files `AGENTS.md: {instructions}`.
  - env: `HOME={workspace}/.home`, `HERMES_HOME={workspace}/.home/.hermes`, `TIRITH_ENABLED=0`, `HERMES_YOLO_MODE=1`, `HERMES_ACCEPT_HOOKS=1`, `HERMES_INFERENCE_PROVIDER=anthropic`.
- run.sh:
  - Place the artifacts, then `export ANTHROPIC_BASE_URL="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"`.
  - Unset `ANTHROPIC_TOKEN` and `CLAUDE_CODE_OAUTH_TOKEN`.
  - Run `python3 adapter.py | python3 report.py`.
- adapter.py:
  - Read line 1 (the request) and spawn `hermes acp --accept-hooks` with cwd `$HI_WORKSPACE` and `start_new_session=True`.
  - Send `initialize`, then `session/load` (if `HI_RESUME`; drop the replayed updates) or `session/new`. Print the sessionId at once.
  - Send `session/set_model "anthropic:$HI_MODEL"`, then `session/prompt` with `HI_TASK`.
  - Answer `session/request_permission` with `allow_once`.
  - For each later stdin line, `json.loads` it and send `session/prompt "/steer "+text`.
  - On SIGINT or stdin EOF: send `session/cancel`, wait ≤10 s for the prompt response (treat error -32603 as cancelled), close hermes's stdin, wait ≤15 s, then killpg.
  - Pass every JSON-RPC line through to stdout.
- report.py:
  - Pass lines through, flushing each.
  - resume = the `session/new` result `sessionId`, written to HI_OUTPUT as soon as it is seen.
  - answer = the `agent_message_chunk` text after the last `tool_call`/`tool_call_update` of the main prompt, minus chunks that start with "⏩ Steer queued" or "Queued for the next turn".
  - usage = the prompt result's `usage`.
  - status = ok if the result has `usage`; fail if it has an error and no cancel was sent, or if the text starts with "API call failed"; cancelled if a cancel was sent.
  - cost_usd = `SELECT estimated_cost_usd FROM sessions WHERE id=?` in `$HERMES_HOME/state.db`, diffed against its value before the run (it is cumulative).
- artifacts: users would drop in:
  - `config.yaml` → `.hermes/config.yaml` (MCP servers, hooks, skills dirs, `security.tirith_enabled: false`)
  - `SKILL.md` → `.hermes/skills/<cat>/<name>/SKILL.md`
  - `SOUL.md` → `.hermes/SOUL.md`
  - memories → `.hermes/memories/MEMORY.md`
  - plugins → `.hermes/plugins/…`
- changes from today's folder:
  - (1) The image lacks the `[acp]` extra: install `hermes-agent[anthropic,acp]==0.19.0`. It adds only `agent-client-protocol==0.9.0` (pydantic is already present; 0.7 MB).
  - (2) It uses `HI_SESSION_ID` and writes `session_id`; the new contract is `HI_RESUME` and `resume`.
  - (3) It writes no status, usage or cost, so read state.db.
  - (4) `2>&1` plus "last lines" parsing puts "↪ restored workspace dir" and "API call failed…" into the answer, and exit code 1 is never reported as a failure.
  - (5) It is missing `--no-restore-cwd`.
  - (6) There is no `TIRITH_ENABLED=0`, so it tries the 38 MB GitHub download on every fresh home.
  - (7) The session id appears only at exit, so it is lost if the run is killed; ACP gives it at about 3 s.
  - If ACP is not adopted, keep chat -q as tier **continued** with fixes 2–6.

## Evidence
- Setup: installed `/root/.local/bin/hermes` v0.19.0 (uv tool, extras=[anthropic]); `acp --check` failed until `agent-client-protocol==0.9.0` was put in `work/hermes/acpdeps` via `PYTHONPATH`. Clean env (work-dir HOME/HERMES_HOME, CLAUDE*/CCR*/ANTHROPIC*/OPENAI* stripped), host-logging CONNECT proxy, claude-sonnet-4-6.
- `chat -q "Reply with just the word PONG." -Q --yolo --provider anthropic -m claude-sonnet-4-6`: stdout "⚠ tirith…" + "PONG."; stderr `session_id: 20261020_044000_1e9d18`; rc 0, 17.5 s. Hosts: api.anthropic.com ×4, pypi.org, github.com ×4, release-assets ×2. Bogus `ANTHROPIC_BASE_URL=https://llm-gw.example.com`: 9 CONNECTs there, rc 1, stdout "API call failed after 3 retries: Connection error."
- ORCHID: run 1 "OK"+"BANANA"; `--resume` run "ORCHID"+"BANANA"; `-c` took the wrong (latest) session and its cwd. SIGINT (chat -q): 4 lines at 17.6 s → rc 130 in 2.1 s, still 4 → resumed run named number 4.
- ACP steer (plan, tool_call ×8, tool_call_update ×8, agent_message_chunk ×37, usage_update ×3, session_info_update): steer 36.1 s, DONE 40.1 s, end_turn 51.6 s, usage {inputTokens 138669, outputTokens 2314}; 3 lines; stdin close → rc 0 in 0.8 s.
- ACP cancel: error -32603 in 1.6 s, 3 lines; `session/load` in a new process replayed history, then answered "got as far as writing 3 numbers". ACP SIGINT to group: kept running to 30, rc 0 after 87 s.
- ACP bogus `ANTHROPIC_BASE_URL=…/v1`: calls to that host + models.dev, openrouter.ai, api.anthropic.com ×1; end_turn with error text, no usage. DeepSeek via `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`: "PONG", rc 0.
- Cleanup: tirith binary deleted; no key in any file; work dir 29 MB.
