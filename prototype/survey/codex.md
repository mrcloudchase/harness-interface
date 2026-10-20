# Codex — codex-cli 0.163.0 tested (pin: @openai/codex@0.163.0)

**Verdict:** works with caveats. The headless path is solid. Today's folder has four real bugs: it ignores the provider URL, puts the request JSON into the prompt, writes the key to disk, and starts the sandbox in a mode that can't run in our container.
**Tier:** steered. Through `codex app-server`, `turn/steer` stopped the count at 3 and done.txt=DONE. Tested on OpenAI and on DeepSeek, without caps or userns, and the key never reached any process environ or file. `continued` is also proven: SIGINT on `codex exec` exits in 0.4 s, and `exec resume <id>` then says how far it got.

## Inputs
- `codex exec [flags] "<task>"`. If stdin is piped as well, it is **appended to the prompt as a `<stdin>` block** (proven: the request JSON came back verbatim). Always run it with `</dev/null`.
- Headless flags: `--json` (JSONL on stdout), `--skip-git-repo-check`, `-m <model>`, `-C/--cd <dir>`, `--ephemeral` (no session files); `-c key=value` sets any config value.
- No prompts: `--dangerously-bypass-approvals-and-sandbox`, or `-s danger-full-access -c approval_policy="never"`. `workspace-write` uses bwrap, which **fails every command in our container**: simulated with no caps, no_new_privs and `max_user_namespaces=0`, it gave `bwrap: Creating new namespace failed … (ENOSPC)`, exit 1. `danger-full-access` works under the same restrictions.
- A built-in exec policy can still refuse commands, even with full access: it refused `rm -f count.txt` ("rm -f style commands are not permitted").
- Instructions: `$CODEX_HOME/AGENTS.md` (global) and `<cwd>/AGENTS.md` (project) both load, and the model followed both (answer ended with GLOBAL-ALPHA and WS-BETA). app-server's `thread/start` also takes `baseInstructions`/`developerInstructions` (not tested).

## Provider
- Speaks the **OpenAI Responses API only**: `wire_api = "chat"` is a hard config error ("no longer supported"), so chat-completions-only endpoints won't work. DeepSeek's `https://api.deepseek.com/v1/responses` works (deepseek-chat counted, steered and ran tools).
- **Key**: the built-in provider ignores `OPENAI_API_KEY` (401 "Missing bearer"). Working ways: `CODEX_API_KEY` (exec only), `codex login --with-api-key` (writes `$CODEX_HOME/auth.json`), app-server `account/login/start {"type":"apiKey","apiKey":…}`; a custom provider's `env_key="<VAR>"` was not tested.
- **URL**: the `OPENAI_BASE_URL` env var is **ignored** (a run with OPENAI_BASE_URL=…/zz succeeded against api.openai.com). Honoured: `-c openai_base_url="…"`, which needs the `/v1` because codex appends `/responses` (without it: 404 at `https://api.openai.com/responses`); or a custom provider: `model_provider="hi"`, `model_providers.hi.{name,base_url,wire_api="responses"}`, plus `env_key` or `requires_openai_auth=true` (uses the logged-in or ephemeral key).
- Prefer the custom provider: the built-in one tries `wss://…/responses` first, which on DeepSeek meant 405s and 16.5 s lost before the HTTPS fallback. Custom providers don't try websockets.
- No login step needed with CODEX_API_KEY or ephemeral login. Honours `HTTPS_PROXY` (all traffic went through my logging CONNECT proxy).
- **Extra hosts at startup** (default config, API-key auth): `chatgpt.com`, `ab.chatgpt.com`, `github.com` ×4; the github calls clone a 103 MB plugins repo into `$CODEX_HOME/.tmp/plugins`. `features.plugins=false`, `features.api_key_model_discovery=false` and `analytics.enabled=false` leave **only the provider host** (bisected).
- With the network down it retries without end ("Reconnecting... waiting for network", `willRetry`; feature `unbounded_connection_retries`=true), so only the run timeout stops it. `--disable unbounded_connection_retries` not tested.
- Models: gpt-5-mini has no bundled metadata (warning "Model metadata for `gpt-5-mini` not found") and in that state couldn't call namespaced MCP tools (fumbled 92 s); gpt-5.5 called the same tool first try. `model_catalog_json` can supply metadata (not tested).
- **Where the key ends up**: `login --with-api-key` writes it to `$CODEX_HOME/auth.json`, which in today's folder is `<workspace>/.home/.codex`, on disk across turns. `CODEX_API_KEY` stays off disk but the model's shell inherits it (`printenv` listed it). Ephemeral app-server login (`-c cli_auth_credentials_store="ephemeral"`; valid values file|keyring|auto|ephemeral) wrote no auth.json and left the key in no file and no `/proc/*/environ`. The prior survey saw the key in `shell_snapshots` when it was in app-server's env; my final scan found it nowhere.

## Artifacts it loads
- `$CODEX_HOME/config.toml` (CODEX_HOME defaults to `~/.codex`; the dir must exist). Profiles: `-p NAME` layers `$CODEX_HOME/NAME.config.toml` (from `--help`; not tested).
- MCP: `[mcp_servers.<name>] command=… args=[…]` in config.toml. A Python stdio server's `secret_word` tool was called (MANGO-42).
- Skills: all four loaded (each listed by name): `$HOME/.agents/skills/<n>/SKILL.md`, `$CODEX_HOME/skills/<n>/SKILL.md`, `<cwd>/.agents/skills/<n>/SKILL.md`, `<cwd>/.codex/skills/<n>/SKILL.md`. Bundled system skills go to `$CODEX_HOME/skills/.system` (500 KB).
- Hooks: `$CODEX_HOME/hooks.json`, Claude-style `{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":…}]}],"UserPromptSubmit":…}}`. They **only ran with `--dangerously-bypass-hook-trust`**; without it, silently skipped. Not tested under app-server.
- `<cwd>/.codex/config.toml`, project hooks and exec rules are ignored until the project is trusted ("Project-local config, hooks, and exec policies are disabled … but skills still load").

## Outputs
- `exec --json` events: `thread.started{thread_id}` (the **first line, ~0.3–1.5 s in**), `turn.started`, `item.started`/`item.completed`, `turn.completed{usage:{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens}}`, `turn.failed{error.message}`, `error{message}`. Item types: agent_message, reasoning, command_execution{command, aggregated_output, exit_code, status}, mcp_tool_call{server, tool, arguments, result, error, status}, error (warnings).
- Answer = the last agent_message (`-o FILE` also writes it). No cost. Exit codes: 0 ok; 1 on turn.failed or config error; 1 on SIGINT (no final event).
- app-server (JSON-RPC over stdio, one object per line) notifications: `thread/started`, `turn/started`, `item/started`/`item/completed` (item.type userMessage, reasoning, agentMessage{text}, commandExecution, mcpToolCall…); deltas, which are most of the traffic (`item/agentMessage/delta`, `item/reasoning/summaryTextDelta`, `item/commandExecution/outputDelta`); `thread/tokenUsage/updated{tokenUsage:{total,last}}` (total is cumulative over the thread); `thread/status/changed`; `turn/completed{turn:{id,status:"completed"|"interrupted"|"failed",error}}`; `warning`, `configWarning`, `error{error,willRetry}`. The thread id is in the `thread/start` response, before any turn.

## State it keeps
- All under `$CODEX_HOME`: transcripts `sessions/YYYY/MM/DD/rollout-<ts>-<thread_id>.jsonl` (they record `turn_aborted` too); databases `state_5`, `logs_2`, `thread_history_1`, `goals_1`, `memories_1`, `queue_1` (`.sqlite`); `models_cache.json` (only with discovery on), `installation_id`, `shell_snapshots/`, `skills/.system`.
- About 4–5 MB per conversation (+103 MB with plugins on). Nothing written to the cwd beyond what the model does. CODEX_HOME under `/tmp` gives a harmless "Refusing to create helper binaries under temporary dir" warning.

## Continue
- `codex exec resume <thread_id> [flags] "<task>"` (`--last` also exists). Proven: run 1 "Remember the word ORCHID. Reply OK." gave thread 01a157a3-0991…; run 2 resumed it and answered "ORCHID", re-announcing the same thread_id in `thread.started`.
- app-server: `thread/resume {threadId, cwd, approvalPolicy, sandbox, model}` works across processes (proven earlier and again via the adapter).

## Mid-turn steering
- Protocol (app-server, verified): `initialize {clientInfo, capabilities:{experimentalApi:true}}`, notify `initialized`; `account/login/start {type:"apiKey",apiKey}` → `{type:"apiKey"}` then `account/login/completed{success:true}`; `thread/start {cwd, approvalPolicy:"never", sandbox:"danger-full-access", model}`; `turn/start {threadId, input:[{type:"text",text}]}` → `turn.id`.
- **`turn/steer {threadId, expectedTurnId, input:[…]}`** → `{turnId}`; the text lands as a userMessage item in the same turn. `turn/interrupt {threadId, turnId}` → `{}`, then `turn/completed` with status `interrupted` within 30 ms.
- Errors (code -32600): "no active turn to steer" / "…to interrupt" once the turn has ended; "expected active turn id `X` but found `Y`" for a wrong id.
- Test (prototype `work/codex/proto/adapter.py`, steer line sent at count=3): gpt-5-mini ended 8.7 s later with count=3, done.txt=DONE, status ok. deepseek-chat: count=3, DONE. With no caps or userns: count=3, DONE.

## Graceful stop
- Plain `codex exec --json` + SIGINT to its process group: exits in **0.4 s, rc=1**, no `turn.failed`/`turn.completed`. The rollout is saved (ends in `turn_aborted`). Resumed answer: "…write numbers 1–30… I completed writing 1 and 2… interrupted while attempting 3" (count.txt had 1 2 3). **Pass.**
- app-server: `turn/interrupt` is graceful, and closing its stdin exits rc 0. **SIGINT to its group kills it mid-request**, so the adapter must start it in its own group (`process_group=0`). With that, SIGINT to the run exited the adapter in 0.1 s with the thread saved; resumed answer "…wrote 1 and 2 before the run was interrupted during the third write". **Pass.** EOF on stdin: same, 0.1 s.

## Worst case
Not needed: `exec resume <id>` and `thread/resume` both restore the full rollout from `$CODEX_HOME/sessions`, which lives in `.home` and survives between turns.

## The folder we should ship
- **harness.json**: `provider: openai` (default `https://api.openai.com/v1`; any Responses endpoint works); `run.interrupt: "steered"`; `run.stdout: application/x-ndjson`; `run.env: {HOME: "{workspace}/.home", CODEX_HOME: "{workspace}/.home/.codex"}`. Instructions go to `.home/.codex/AGENTS.md`, not the workspace's AGENTS.md (which would overwrite the project's own): as a `files` entry if files may target `.home/`, else adapter.py writes it from the request.
- **run.sh**: artifacts loop; `mkdir -p "$CODEX_HOME"`; `exec env -u HI_PROVIDER_KEY python3 "$HI_HARNESS_DIR/adapter.py" 3<<<"$HI_PROVIDER_KEY"`, so the key travels on fd 3 and is in no process's environ (verified).
- **adapter.py** (prototype tested, 100 lines, `work/codex/proto/adapter.py`):
  - Start: read the key from fd 3; spawn `codex app-server -c cli_auth_credentials_store="ephemeral" -c analytics.enabled=false -c features.plugins=false -c features.api_key_model_discovery=false` plus the custom provider `model_providers.hi` (`base_url=$HI_PROVIDER_URL`, `wire_api="responses"`, `requires_openai_auth=true`), with `process_group=0` and an env without the key; log in with `account/login/start`.
  - Turn: `thread/resume` if `HI_SESSION_ID` is set, else `thread/start` (`sandbox:"danger-full-access"`, `approvalPolicy:"never"`); **write `HI_OUTPUT` with the thread id at once**; `turn/start` with line 1's `task`.
  - Steer: each later stdin line (a JSON string) → `turn/steer`; if refused (the turn just ended), queue it and `turn/start` it after `turn/completed`.
  - Stop: SIGINT or EOF → `turn/interrupt`, wait for `turn/completed`, close app-server's stdin. **Done condition: `turn/completed` for the current turn with nothing queued.** Approval requests get accept (none appeared with approvalPolicy never). Notifications pass through to stdout unchanged.
- **report.py** (folded into adapter.py): answer = last `item/completed` agentMessage text; usage = latest `thread/tokenUsage/updated` `.total` (cumulative over the thread; subtract the turn-start value for per-turn); status = `ok` if the turn status is `completed`, else `fail`; session_id/resume = thread id, written early; no cost. Plain-exec path: id from thread.started, usage from turn.completed.usage, turn.failed = fail.
- **artifacts**: `config.toml` → `.codex/config.toml` (the three network-off settings plus `[mcp_servers.*]`); skills → `.agents/skills/<n>/SKILL.md` or `.codex/skills/<n>/SKILL.md`; `AGENTS.md` → `.codex/AGENTS.md`; `hooks.json` → `.codex/hooks.json` (needs hook trust, above); `NAME.config.toml` profiles → `.codex/`.
- **Changes from today's folder** (`harnesses/codex/`):
  - (1) `OPENAI_BASE_URL` is ignored, so every provider URL silently went to api.openai.com: use a custom provider, or at least `-c openai_base_url`.
  - (2) Missing `</dev/null`: the server's request JSON is appended to the prompt.
  - (3) `codex login --with-api-key` stores the key in `.home/.codex/auth.json` in the workspace. Use ephemeral login (app-server) or `CODEX_API_KEY` (exec; the shell sees it, so add `-c shell_environment_policy.exclude=["CODEX_API_KEY"]` — not tested).
  - (4) `resume --last` should be `exec resume "$HI_SESSION_ID"`. (5) AGENTS.md is written into the user's workspace.
  - (6) No network-off settings: github, chatgpt and ab.chatgpt are contacted, and the 103 MB plugins clone fails or stalls behind the egress proxy.
  - (7) No `run.interrupt`, no adapter, nothing marks an interrupted run. (8) The sandbox-bypass flag is right; keep it (workspace-write can't work here).

## Evidence
- Clean env everywhere: fresh HOME/CODEX_HOME; inherited CLAUDE*/CCR*/OPENAI*/CODEX*/key variables stripped; HTTPS_PROXY → my logging CONNECT proxy; one-word-answer prompts.
- Auth: `exec` with OPENAI_API_KEY only → rc=1, 401 ×5 (websocket, then HTTPS). With CODEX_API_KEY → rc=0, "PONG" at 4.2 s.
- Hosts: default → chatgpt.com ×3, ab.chatgpt.com, github.com ×4, api.openai.com; with `--disable api_key_model_discovery --disable plugins -c analytics.enabled=false` → api.openai.com only.
- URL: OPENAI_BASE_URL=…/zz → success against the default (env ignored); `openai_base_url=…/yy` → 404 at `…/yy/responses`; without /v1 → 404 at `/responses`.
- Providers: custom `hi` → OpenAI with `env_key=HI_PROVIDER_KEY` → PONG; DeepSeek `wire_api="chat"` → config error, rc=1; DeepSeek `wire_api="responses"` → PONG in 1.1 s.
- Sandbox (no caps, userns limit 0, nocaps.sh): `-s workspace-write` → bwrap ENOSPC, exit 1; `-s danger-full-access` → a.txt written.
- Artifacts: two AGENTS.md → both tokens appended; four skill dirs → all listed; MCP → works with gpt-5.5 (`mcp_tool_call` completed, MANGO-42), fails with gpt-5-mini; hooks → ran only with the trust bypass (both marker files created).
- stdin: piping `{"task":…,"metadata":{"tag":"ZEBRA-77"}}` → the model quoted it back as a `<stdin>` block.
- Continue: ORCHID passed via `exec resume <id>`. SIGINT on exec (gpt-5-mini): sent at count=3 (19.5 s), exit 0.4 s later, rc=1; resumed answer named the counting and "1 and 2… attempting 3".
- Adapter (stdin line 1 = request, line 2 = steer JSON string): steer → count=3, done.txt=DONE, rc=0; same on deepseek-chat and under nocaps.sh. SIGINT: first attempt killed app-server (same group, RPC timeout); after `process_group=0`, exit in 0.1 s, rc=1, resume answered "wrote 1 and 2… interrupted during the third write". EOF: exit in 0.1 s. Late-steer probe: "no active turn to steer", "no active turn to interrupt", "expected active turn id `X` but found `Y`".
- Key: no key in any run process's `/proc/*/environ` or in any file under the work dir or `validate/codex`. Caches and plugin clones deleted; work dir is 89 MB.
