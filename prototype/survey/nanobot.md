# nanobot — nanobot 0.3.5 (pin: nanobot-ai==0.3.5)

**Verdict:** works with caveats. Headless `agent -m` works but has no structured output, exits 0 on model errors and runs tools in its own workspace. `nanobot gateway` plus its WebSocket channel fixes all three, so it is the mode to ship, through an adapter.py.
**Tier:** steered. A second `{"type":"message"}` on the same `chat_id`, sent while the count was running, was injected mid-turn. Counting stopped at 4 of 30 and done.txt was written. Passed twice, once through a prototype adapter driven from stdin.

## Inputs
- Headless: `nanobot agent --no-markdown -m "<task>" -s <session> [-w <dir>] [-c <config>]`. The task is an argument. Without `-m` it starts a TUI that needs a TTY. `--classic` reads from a TTY prompt and waits for each turn to end.
- There are no approval prompts: tools (exec, edit_file, apply_patch, web, …) always run. `tools.restrictToWorkspace` defaults to false and `tools.exec.timeout` to 60s.
- There is no model flag. The model is set in config at `agents.defaults.model` (`anthropic/claude-sonnet-4-6`) together with `agents.defaults.provider`.
- Working dir: tools run in the "nanobot workspace", `agents.defaults.workspace` (default `~/.nanobot/workspace`), not in the cwd. `-w <dir>` moves them, but then it writes SOUL.md, USER.md, HEARTBEAT.md, AGENTS.md (template), memory/, prompts/, skills/ and .nanobot/workspace-id into `<dir>`, plus a dulwich `.git` when `<dir>` is not inside a repo. Seen in ws2.
- Gateway fix: each WS message can carry `"workspace_scope":{"project_path":"<abs dir>","access_mode":"full"|"restricted"}`. Tools then run there (`pwd` = request workspace), and nothing else is written to it (ws3, ws8: only count.txt and done.txt).
- Instructions: `AGENTS.md` is read from the project root (the `-w` dir, or the scope's `project_path`). `SOUL.md` and `USER.md` are read from the nanobot workspace. Template-identical files are skipped. The model follows them: "End every reply with PINEAPPLE" worked under `-m -w` (2/2) and via the gateway scope ("4\n\nPINEAPPLE"; I checked the captured system prompt).

## Provider
- It speaks Anthropic Messages (`providers.anthropic`, backend `anthropic`), OpenAI chat completions and Responses (`providers.openai`, `apiType` auto|chat_completions|responses), any OpenAI-compatible endpoint (`providers.custom`), and many named ones (`deepseek`, …).
- It has no provider env vars. Its `ANTHROPIC_API_KEY` registry entry is not read. The provider is configured in config.json: `providers.<name>.apiKey` and `.apiBase`.
- **`${VAR}` references in config.json are resolved from the environment at load.** `"apiKey":"${HI_PROVIDER_KEY}","apiBase":"${HI_PROVIDER_URL}"` worked, and grep found no key on disk. `NANOBOT_*` env (pydantic-settings) applies only when no config file exists (from source; not tested).
- URL: anthropic strips a trailing `/v1`, so either form works. openai, custom and deepseek pass `apiBase` straight to the OpenAI SDK, so OpenAI wants `https://api.openai.com/v1`. I tested gpt-5-mini and deepseek-chat (`https://api.deepseek.com`) through the real proxy; both replied HELLO.
- No login and no `onboard` needed: a 3-key config.json works. It honors `HTTPS_PROXY`. Through a logging CONNECT proxy, the only host contacted was `api.anthropic.com:443`, with no update check or telemetry. Web tools use duckduckgo and r.jina.ai only when called.

## Artifacts it loads
- `$HOME/.nanobot/config.json`, or `-c`. It holds MCP servers (`tools.mcpServers`), exec/web settings, `agents.defaults.disabledSkills` and `modelPresets`.
- Skills: `<nanobot workspace>/skills/<name>/SKILL.md`, alongside the built-in ones. Prompt overrides: `<nanobot workspace>/prompts/*.md` (dream.md, evaluator.md).
- Persona and user files: `<nanobot workspace>/SOUL.md` and `USER.md`. Project `AGENTS.md` comes from the project root (see above). No config-file hooks (hooks are Python only).

## Outputs
- `-m`: plain text. The first run prints "  Created SOUL.md…" lines to stdout, then the banner `🐈 nanobot`, then `  ↳ <tool hint>` lines and the answer. Logs go to stderr.
- `-m` exit codes: 0 on success **and 0 on model errors**, where the "answer" is `Error calling LLM: Connection error.`. SIGINT gives 130. No usage or cost on stdout; `_last_usage` is in the session jsonl metadata line.
- Gateway WS (JSON frames, `event` key):
  - Start: `ready{chat_id,client_id}`, then `attached{chat_id}` after `attach`.
  - During the turn: `turn_model_updated`, `goal_status{running|idle}` and `retry_status`; `delta{text}` and `stream_end{stream_id,resuming?}` (answer text = the deltas); `message{text,tool_events,kind:"tool_hint"|"progress"}`.
  - End: `turn_end{latency_ms,usage{prompt_tokens,completion_tokens,total_tokens,request_count,cached_tokens,cache_write_tokens,…}}`, then `session_updated`.
- No cost anywhere.
- Model error over WS: `turn_end` with all-zero usage and no text. The error is only in the gateway log; the transcript gets "[Assistant reply unavailable due to model error.]".
- Resume id = `chat_id`, known at `ready`, before any model call.

## State it keeps
Everything is under `$HOME/.nanobot/`:
- `config.json` and `llm_usage.sqlite3` (per-call tokens).
- `sessions/<workspace-id>/<base64url(session key)>.jsonl`: transcripts. The key is `-s` value, or `websocket:<chat_id>`.
- `webui/websocket_<chat_id>.jsonl`: WS event log.
- `run/gateway.json` (singleton guard: a leftover gateway makes `nanobot gateway` print "Gateway is already running" and exit), `cron/` and `cli-apps/`.
- `workspace/`: the templates, memory/MEMORY.md, history.jsonl, triggers/ and cron/jobs.json.

Nothing is written to the request workspace in gateway+scope mode. "Dream" memory consolidation (`agents.defaults.dream.enabled`) and heartbeat (`gateway.heartbeat.enabled`) should be turned off.

## Continue
- `-m` mode: `-s <id>` again resumes. Run 1 "Remember the word ORCHID. Reply OK." gave OK; run 2 with the same `-s` gave "ORCHID."; with a different `-s` it gave UNKNOWN.
- Gateway: a new gateway process, `{"type":"attach","chat_id":X}`, then a message on X. Through the adapter, run 2 answered "The word you asked me to remember is **ORCHID**." The handle is the chat_id from `ready`.

## Mid-turn steering
- Protocol: `nanobot gateway` with `channels.websocket {enabled, host 127.0.0.1, port P, websocketRequiresToken:false}`. Connect to `ws://127.0.0.1:P/?client_id=hi` and read `ready`.
- Task: `{"type":"message","chat_id":C,"content":TASK,"workspace_scope":{"project_path":WS,"access_mode":"full"}}`.
- Steer: `{"type":"message","chat_id":C,"content":TEXT}` while it runs. AgentLoop puts it on the session's pending queue (maxsize 20) and injects it as a user message before the next model call; the transcript shows it after the tool result for 4.
- Result: after 3 numbers, the steer went in. Count ended at 1 2 3 4, done.txt = DONE, and the reply was "counting has stopped at 4". The turn took 22s (direct WS client) and 24s (adapter).
- `access_mode:"full"` is only granted to localhost TCP peers. Over `unixSocketPath`, full is refused ("full workspace access is unavailable") and restricted works. AF_UNIX paths are limited to 108 chars.
- The `websockets` client honors `HTTPS_PROXY` (HTTP 502 from the proxy), so it must connect with `proxy=None`.
- `nanobot serve` (OpenAI API) and `agent -m` use `process_direct`, which has no pending queue, so they cannot be steered.

## Graceful stop
- Its own stop is `{"type":"message","chat_id":C,"content":"/stop"}`, a priority command. It answers at once with `message{"text":"Stopped 1 task(s)."}` and `goal_status idle`; no `turn_end` follows.
- A resumed run then said "…writing the numbers 1 to 30 to count.txt … only got as far as writing **3**" (pass). The saved context is lossy, though: only the last tool round is kept, so the model thought 1–2 were skipped.
- SIGINT to the gateway's group: exit 0 in about 2s, after "Shutdown: flushed 2 session(s) to disk". SIGINT to the gateway in the middle of a turn without `/stop` was not tested.
- SIGINT to `agent -m` (process group, at count 3): exit 130 after 0.5s, with count still 3. The session kept the user message plus the last tool call, marked "Task interrupted"; resumed with `-s`, it named the counting and number 3 (pass, also lossy).

## Worst case
Not needed: both modes resume. As a fallback, the session jsonl (role/content/tool_calls) can be handed back as context.

## The folder we should ship
- **harness.json:**
  - `provider: anthropic`, `run.interrupt: "steered"`, `run.stdout: "application/x-ndjson"`.
  - env `HOME={workspace}/.home`; `COLUMNS` is no longer needed.
  - files: put `{instructions}` in `.home/.nanobot/workspace/USER.md`, not AGENTS.md. With the scope, AGENTS.md is read from the request workspace, and writing there would show as a user change. USER.md is loaded from the nanobot workspace (from source; not tested live).
- **run.sh:**
  - Place artifacts as now.
  - Write config.json with `"apiKey":"${HI_PROVIDER_KEY}","apiBase":"${HI_PROVIDER_URL}"` (no secret on disk), `model anthropic/<HI_MODEL>`, dream and heartbeat off, random free `gateway.port` and `channels.websocket.port` on 127.0.0.1, `websocketRequiresToken:false`.
  - exec adapter.py with nanobot's own interpreter, `$(head -1 "$(command -v nanobot)" | cut -c3-)`, which has websockets 16.
- **adapter.py** (prototype, tested: `work/nanobot/proto/adapter.py`):
  1. Start `nanobot gateway` (new session, stdout and stderr to stderr) and poll-connect with `proxy=None`; it was up in about 1.5–1.8s.
  2. Read `ready` and emit `{"event":"session","chat_id":C}` at once. C = HI_RESUME when set, followed by `attach`.
  3. Send the task with workspace_scope = HI_WORKSPACE, full.
  4. Echo every frame as NDJSON. Each later stdin line (a JSON string) is sent as a message on C.
  5. On SIGINT or EOF, send `/stop` and end on "Stopped …". Otherwise end at `turn_end`, then drain for 1s.
  6. SIGINT the gateway group and wait (it exits 0). Kill it in `finally`, or the singleton guard blocks the next start.
- **report.py:**
  - answer = concatenated `delta.text` of the last stream segment (or all deltas after the final tool round).
  - resume = `chat_id` from the first `session` line; write it early.
  - usage = `turn_end.usage` (prompt, completion and cached tokens); cost_usd = null.
  - status = fail when there is no `turn_end`, or when usage is all zero with no text (model error), and "stopped" on "Stopped N task(s)." Never trust the exit code.
- **artifacts:** skills go to `.nanobot/workspace/skills/<name>/SKILL.md`, MCP servers are merged into config.json `tools.mcpServers` (run.sh must merge, not overwrite), and prompt overrides go to `.nanobot/workspace/prompts/`.
- **changes from today's folder:**
  - It writes the raw key into config.json; use `${…}` refs instead.
  - Tools run in `.home/.nanobot/workspace`, not the request workspace; add workspace_scope via the gateway.
  - It reads `HI_SESSION_ID`, which is not in the contract (use HI_RESUME), so it never resumes.
  - report.py writes `session_id` instead of `resume`, has no usage, and marks "Error calling LLM…" as ok, since the answer is non-empty and the exit is 0.
  - `onboard` is unnecessary. It is `responded`-only; it can be `steered`.
- **Untested in the real sandbox:** loopback availability (the gateway binds two 127.0.0.1 ports), a read-only root, and a stale `run/gateway.json` left in the persistent `.home`.

## Evidence
- Install and help: `nanobot --version` gave v0.3.5 (uv tool at /root/.local/share/uv/tools/nanobot-ai). `--help`, `agent --help` and `gateway --help` read.
- `agent -m "Reply with exactly: HELLO"` with the 3-key `${VAR}` config: exit 0, HELLO, about 5s. Logging proxy saw only `CONNECT api.anthropic.com:443`. Key grep over work dir: none.
- ORCHID: `-s orchid` twice gave "OK." then "ORCHID."; `-s other` gave UNKNOWN. Adapter with HI_RESUME=chat_id gave ORCHID.
- `-w ws2`: pwd = ws2, PINEAPPLE followed, and ws2 was polluted with SOUL.md, USER.md, HEARTBEAT.md, memory/, prompts/, skills/, .nanobot/.
- Steering:
  - Gateway WS client (`tools/wsclient.py`): steer at count 3 (t=14.8s); exec `echo 4`, then `echo DONE > done.txt`; `turn_end` at 22.1s with prompt_tokens 69610. Final count 4, done.txt present.
  - Adapter (`proto/drive.py p1`): steer line on stdin at count 3 (t=17.6s). Events: message 12, delta 11, stream_end 7, turn_end 1. Count 4, done.txt present, gateway exit 0.
- Stop:
  - `/stop` at count 3 gave "Stopped 1 task(s)." at t=13.5s, and the count stayed 3. After a gateway restart with `attach`, it named counting and 3.
  - Adapter SIGINT (p2): stopped 0.8s after the signal, adapter exit 0; resume (p3) named counting and 3.
  - `agent -m` SIGINT: exit 130 in 0.5s.
- Bad key through the adapter: `turn_end` usage all 0, no text; gateway log: `authentication_error`.
- OpenAI (`providers.openai`, apiBase …/v1, gpt-5-mini) and DeepSeek (`providers.deepseek`) gave HELLO.
- Cleanup: gateways and the logging proxy were stopped, the /tmp/nbsv-*.sock files deleted, and no keys are on disk. Work dir is about 1.1 MB.
