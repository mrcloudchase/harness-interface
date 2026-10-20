# OpenSquilla — opensquilla 0.5.6 (pin: 0.5.6)

**Verdict:** works with caveats. Headless `agent --json` and resume work. Steering works only through `opensquilla gateway run` plus a WebSocket adapter. AGENTS.md reaches the model as low-priority "request context", and the model ignored it.
**Tier:** steered. Tested live: `sessions.steer.v2` on the gateway after 3 numbers stopped the count at 4 and wrote done.txt. `continued` also passes (SIGINT gives exit 130 and the session is saved).

## Inputs
- `opensquilla agent -m TEXT` (required; it does not read the task from stdin). One turn, `--unattended` by default (never asks). `--permissions restricted|bypass|full` (env `OPENSQUILLA_AGENT_PERMISSIONS`). `bypass` ran the shell with no prompt and no bwrap ("Run mode: Full Host Access").
- `--model`, `--workspace DIR` (tool root; it turns on `--workspace-strict`), `--session-id`, `--session-db-path` (default `:memory:`, which means no resume), `--timeout/-T`, `--max-iterations`, `--thinking`, `--no-memory-capture`, `-f FILE`, `--json`, `--event-stream-stderr`, `--transcript-path`, `--usage-path` (the last two are not tested).
- `--stateless-keep-project-rules`: loads only AGENTS.md, keeps memory under state/, and does not seed the workspace (recommended).
- Instruction file: `AGENTS.md` in `--workspace` (full mode also loads SOUL.md, IDENTITY.md, USER.md and MEMORY.md). It is NOT put in the system prompt. It goes into the first user message as `[Request context for this turn] ... Use it only when it is relevant` → `## Workspace Files (injected)`, wrapped in `<untrusted source='workspace:AGENTS.md'>`. I saw this with a local sink. claude-sonnet-4-6 ignored "begin every reply with BANANA / answer in French" in full mode, in stateless mode, and with `[safety] wrap_untrusted_workspace=false`. `[[agents]] system_prompt` had no effect (checked with the sink). When the rules were prepended to `-m`, BANANA was obeyed and French was not.

## Provider
- `[llm] provider = "anthropic"` speaks Messages and POSTs `{base_url}/v1/messages`. A base with or without `/v1` both work (`_api_url` removes a duplicate `/v1`). `"openai_responses"` speaks Responses, base `https://api.openai.com/v1`; gpt-5-mini OK. `"openai"` speaks chat completions; gpt-5-mini failed with `invalid_stream_order`. The registry also has deepseek, openrouter, litellm_proxy and others.
- Key: `api_key_env = "ANTHROPIC_API_KEY"` names the env var. No login step. The key was found in no file (I scanned every file the runs wrote).
- Proxy: `HTTPS_PROXY` is ignored (`env.proxy_ignored`) unless `OPENSQUILLA_TRUST_ENV=1`.
- Other hosts (logging CONNECT proxy, LLM pointed at a local sink):
  - CLI with defaults: `telemetry.opensquilla.ai:443` (3 times). `OPENSQUILLA_TELEMETRY_DISABLED=1` stops it.
  - Gateway: `mobile.events.data.microsoft.com:443` (1DS telemetry from onnxruntime 1.31, loaded for memory embeddings). `ORT_DISABLE_TELEMETRY=1` stops it.
  - With both set: nothing but the provider (one run each). Also set `OPENSQUILLA_UPDATE_CHECK_DISABLED=1` (no update traffic seen) and `[squilla_router] enabled=false`.
- Gateway only: by default each new session makes one extra LLM call to title it (`session_naming.*` logged 3 times). `[naming] enabled = false` turns it off.

## Artifacts it loads
- Config: `$HOME/.opensquilla/config.toml`. The root can be overridden by `OPENSQUILLA_STATE_DIR`, or by `OPENSQUILLA_HOME` with `OPENSQUILLA_PROFILE` (`--profile`).
- Skills (`<name>/SKILL.md`): `$HOME/.opensquilla/skills/`, `$HOME/.agents/skills/`, `<workspace>/.agents/skills/`, `<workspace>/skills/`.
- MCP: inside config.toml: `[mcp] enabled=true` plus `[[mcp.servers]]` with name, transport `stdio|sse`, command, args, url and env. Env prefix `OPENSQUILLA_MCP_`.
- Hooks / custom commands: none found in the config schema.
- Workspace files: AGENTS.md (plus SOUL.md, IDENTITY.md, USER.md, MEMORY.md and `memory/**/*.md` in full mode).

## Outputs
- `--json` prints ONE object at the end, with these fields:
  - `status` (`ok` or `error`), `agent_id`, `session_key`, `text`, `errors[{message,code}]`, `workspace`, `routing`, `artifacts`.
  - `usage{input_tokens, output_tokens, total_tokens, reasoning_tokens, cached_tokens, cost_usd (estimate), billed_cost, model, request_count, model_usage_breakdown[]}`.
- `text` often starts with a `[[reply_to_current]]` delivery tag. Strip it with `\[\[\s*(?:reply_to_current|reply_to\s*:\s*[^\]\n]+)\s*\]\]\s*`.
- `--event-stream-stderr` writes v1 JSONL to stderr, mixed with log lines: `{"_event":true,"schema_version":1,"kind":...}`.
  - Kinds: `text_delta` (no text in it!), `tool_use_start{tool_use_id,tool_name,started_at}`, `tool_result{...,is_error}`, `done`, plus router, thinking, warning and error. It is low-sensitivity, so it carries no text and no ids.
- Exit codes: 0 when ok. 1 on error, with the JSON still printed (`status:"error"`, e.g. code `"400"`). SIGINT gives 130 and NO stdout.
- Gateway WS events:
  - `task.queued` (has `session_key`, `session_id`, `turn_id`) and `task.running` (`steer_capability{mode:"same_turn",expected_turn_id}`).
  - `session.event.input_disposition`, `state_change`, `provider_activity`, `text_delta`, `tool_use_start/end`, `tool_result` (with arguments and result).
  - `session.event.done{text, input_tokens, output_tokens, cached_tokens, cost_usd, model, session_totals, ...}` and `session.event.error{message,code}`.

## State it keeps
- Under `$HOME/.opensquilla/`:
  - `sessions.db` (only the path given to `--session-db-path`), `state/sessions.db` (gateway sessions).
  - `state/agents/main/{memory.db,turns/<uuid>/<date>.md}`: turn captures, which hold the user's text.
  - `logs/{decisions,traces}-YYYYMMDD.jsonl`, `cache/skills_snapshot.json`, `state/{scheduler.db,approval_queue.sqlite,...}`, `media/`.
- Also `$HOME/.local/state/OpenSquilla/profile-locks/` and `$HOME/.cache/Microsoft/DeveloperTools/.onnxruntime/`.
- Workspace pollution: full mode and the gateway seed `AGENTS.md` (empty when missing), `SOUL.md`, `IDENTITY.md`, `USER.md`, `MEMORY.md` and `memory/.raw_fallbacks/.migrated` into the workspace (missing files only). `--stateless-keep-project-rules` writes nothing there. The gateway always seeds when `workspace_dir` is set; there is no switch.

## Continue
- CLI: pass the same `--session-id X --session-db-path $HOME/.opensquilla/sessions.db` again. ORCHID passed ("The word you asked me to remember is ORCHID"). A different id did not know the word, so this is real replay, not memory.
- The resume id is chosen by the harness, so it is known before the run starts.
- Gateway: `sessions.create` returns `key` (`agent:main:cli:xxxxxxxx`, assigned by the server; no custom key) before any turn. After a gateway restart, `sessions.send` to that key resumed the conversation ("count stopped at 4", done.txt).

## Mid-turn steering
- Only through the gateway. Start it with `opensquilla gateway run --port P` (bind 127.0.0.1; `auth.mode` defaults to `none`, which makes a loopback peer the owner, so no token is needed). It is ready in about 5 s.
- Protocol: WebSocket `ws://127.0.0.1:P/ws`. Frames are `{"type":"req","id","method","params"}` and the replies are `{"type":"res"|"event",...}`. Steps:
  1. Receive the `connect.challenge` event, then send `connect{minProtocol:1,maxProtocol:3,role:"operator",scopes:["operator.admin"]}` and expect `hello-ok`.
  2. Call `sessions.create{agentId:"main",kind:"cli"}`, which returns `{key}`.
  3. Call `sessions.messages.subscribe{key}`.
  4. Call `sessions.send{key,message,client_message_id,surface_id?,_source?}`, which returns `turn_id`.
  5. To steer, call `sessions.steer.v2{key,message,expected_turn_id:turn_id,client_request_id:"steer:<id>",client_message_id:<id>}`. It returns `{accepted:true,disposition:"steering"}`.
  6. To stop, call `sessions.abort{key}`, which returns `{aborted:true,cancelled_tasks:1}`.
- `opensquilla.cli.gateway_client.GatewayClient` (run with `/root/.local/share/uv/tools/opensquilla/bin/python`) wraps all of this: `create_session`, `send_message` (async iterator), `steer_session` and `abort_session`.
- Counting test: PASS. Steered at t=13.8 s with 3 lines. The turn ended at 23.9 s, count.txt held 1–4, done.txt held "DONE", and nothing was added 3 s later.

## Graceful stop
- CLI `agent`, SIGINT to the process group with 3 lines written: exit 130 after 1.5 s, count stayed at 3, nothing on stdout. Resumed with the same id: "I was writing the numbers 1 to 30 to count.txt … confirmed up to 2, possibly 3." PASS.
- Gateway `sessions.abort`: done arrived 0.3 s later. Resumed: it named the counting but gave no number. The model had used one `for` loop, which was killed (`-15`).
- SIGINT to the gateway mid-turn: it exited in 1.6 s. After a restart the same key answered "only gotten through 3 numbers (1, 2, and 3)". PASS.

## Worst case
Not needed: the conversation survives SIGINT, abort and a gateway restart. If it were needed, `state/agents/main/turns/*/*.md` holds turn captures and `--transcript-path` writes JSONL (not tested).

## The folder we should ship
- harness.json: `provider: anthropic`, `run.interrupt: "steered"`, `stdout: application/x-ndjson` (gateway event frames).
  - env: `HOME={workspace}/.home`, `OPENSQUILLA_TRUST_ENV=1`, `OPENSQUILLA_TELEMETRY_DISABLED=1`, `OPENSQUILLA_UPDATE_CHECK_DISABLED=1`, `ORT_DISABLE_TELEMETRY=1`, `NO_PROXY=127.0.0.1,localhost` (the adapter's WebSocket must not go through the proxy).
  - files: keep `AGENTS.md: {instructions}`, but the adapter also prepends its content to the first message of a new session.
- run.sh: put artifacts in place, then write config.toml with:
  - `config_version=2`, `workspace_dir="$HI_WORKSPACE"`.
  - `[llm] provider/model/api_key_env="ANTHROPIC_API_KEY"/base_url="${HI_PROVIDER_URL%/}"`.
  - `[squilla_router] enabled=false`, `[permissions] default_mode="bypass"`, `[naming] enabled=false`.
  - Then append `$HOME/.opensquilla/config.extra.toml` when present (the hook for MCP and other user config).
  - Export the key from `HI_PROVIDER_KEY` and exec `adapter.py` with opensquilla's own Python.
- adapter.py:
  - Note which seed files already exist in the workspace.
  - Start the gateway with `Popen([... "gateway","run","--port",free,"--bind","127.0.0.1"], start_new_session=True)`, logs to `$HOME/.opensquilla/gateway.log`, not stdout. Poll the connect until it works.
  - Use `HI_RESUME` as the key, or call `sessions.create`. Write `{"resume":key}` to `HI_OUTPUT` at once.
  - Subscribe and `sessions.send` line 1's task. Print each event frame as one NDJSON line, flushed.
  - Each later stdin line (a JSON string) becomes `sessions.steer.v2` with the current `turn_id`. If the turn already ended (disposition is not `steering`, or done was seen), it becomes `sessions.send` instead.
  - On SIGINT or EOF: `sessions.abort`, wait for `session.event.done`, SIGINT the gateway's group, then wait.
  - Last, delete the seed files this run created (SOUL.md, IDENTITY.md, USER.md, MEMORY.md, memory/).
- report.py (or the adapter): get the answer from the last `session.event.done.text` (tag stripped). Usage is `input_tokens/output_tokens/cached_tokens` and cost is `cost_usd` from that event. Status is fail when a `session.event.error` arrives, `stopped` on abort. Resume is the key, written early.
- Fallback `continued` command (no gateway): `opensquilla agent --json --permissions bypass --workspace "$HI_WORKSPACE" --stateless-keep-project-rules --session-id "${HI_RESUME:-$(uuidgen)}" --session-db-path "$HOME/.opensquilla/sessions.db" -m "$TASK"`. Write the resume before the run, because SIGINT leaves stdout empty.
- artifacts: skills → `.opensquilla/skills/<n>/SKILL.md` or `.agents/skills/<n>/SKILL.md`. MCP and other config → `.opensquilla/config.extra.toml` (because run.sh overwrites config.toml).
- changes from today's folder:
  - It reads `HI_SESSION_ID` (not part of the contract) instead of `HI_RESUME`.
  - report.py writes `session_id` rather than `resume`, and never writes it early. On SIGINT, stdout is empty, so `HI_OUTPUT` gets `{}` and the session is lost.
  - It doesn't pass `--stateless-keep-project-rules`, so every run seeds SOUL.md, IDENTITY.md, USER.md, MEMORY.md and memory/ into the user's workspace.
  - AGENTS.md alone is ignored by the model. `ORT_DISABLE_TELEMETRY` is missing. `[[reply_to_current]]` is not stripped. `run.interrupt` is not declared. There is no route for MCP or extra config into config.toml.

## Evidence
- Version: `opensquilla version` gives 0.5.6 (uv tool at /root/.local/share/uv/tools/opensquilla). Model claude-sonnet-4-6 throughout.
- ORCHID: run 1 "OK" (28 s, exit 0, cost_usd 0.044); run 2 same id: "…ORCHID" (exit 0). Other id: "I don't have any record".
- AGENTS.md: the decisions log showed `bootstrap_files:[AGENTS.md injected 94 chars]` and the reply was "2 + 2 = **4**." (rule ignored). The sink capture showed the "[Request context for this turn]" framing in `messages[0]`.
- SIGINT (CLI): t=17.8 s → exit 130 after 1.5 s. Stderr kinds: text_delta 12, tool_use_start 3, tool_result 2. count.txt was 1,2,3.
- Steer (gateway): the `sessions.steer.v2` result was `{"status":"accepted","accepted":true,"disposition":"steering","revision":1}`. Events: task.queued 1, task.running 1, state_change 18, tool_use_start 5, text_delta 22, done 1. done.text: "…Stopping the count now.Done. `done.txt` has been written … The count stopped at 4." input_tokens 80640.
- Abort: `{"aborted":true,"cancelled_tasks":1}`, then done 0.3 s later. Resume cost_usd 0.009.
- Egress: CLI with defaults sent 3× CONNECT telemetry.opensquilla.ai. Gateway with the OpenSquilla vars only: 1× mobile.events.data.microsoft.com. With ORT_DISABLE_TELEMETRY=1: none. Without a `/v1` suffix the sink got `POST /v1/messages`.
- OpenAI: `openai_responses` with gpt-5-mini gave ok, "four", cost 0.0023. `openai` (chat) gave error `invalid_stream_order`.
- Scratch work: /tmp/claude-0/-home-user/37719b48-fc3a-58ba-bb72-5869c819d794/scratchpad/harness-survey/work/opensquilla (bin/steer.py is the working steer client; 20 MB).
