# J-Code — jcode v0.95.0 (6487bbd7e, built 2026-10-17) (pin: none, vendor install script, latest)

**Verdict:** works with caveats. Headless `run --ndjson` and resume are solid. The steering path (`api-bridge --stdio`) starts a background daemon that the adapter must manage. With `ANTHROPIC_BASE_URL` set, the model catalog is still fetched from the hard-coded host `api.anthropic.com`.
**Tier:** steered. `soft_interrupt` sent over `api-bridge --stdio` after count=3 was injected at point D. Counting stopped at 3, `done.txt` = DONE, and `turn_done` came 10.2 s later.

## Inputs
- Task: positional argument, `jcode run [--ndjson|--json] <MESSAGE>`. No stdin form was found. Global flags: `-p/--provider`, `-m/--model`, `-C/--cwd` (not tested; cwd works), `--resume <id>`, `--no-update`, `--quiet`, `--tools`/`--tool-profile`/`--disabled-tools`, `--trace`.
- No approval prompts in `run` or the bridge. bash, write and todo ran unasked. The bridge protocol has `permission_request`/`permission_response`, but this was never seen.
- Instructions: `AGENTS.md` in the cwd was read and followed (it said "end with ZEBRA-42" → reply "4\n\nZEBRA-42"). `CLAUDE.md` alone was ignored. The binary also names `~/AGENTS.md`, `./.jcode/prompt-overlay.md`, `~/.jcode/prompt-overlay.md` and `~/.jcode/system-prompt.md` (not tested).
- The model must be one jcode knows for the provider. `claude-haiku-4-5` (alias) and `deepseek-chat` with `-p anthropic-api` both fail: `Failed to select model ...`, exit 1. On resume, `-m` is **silently ignored**: the session keeps its model. It is not refused. A run with `-m claude-haiku-4-5-20251001` still answered as sonnet-4-6.
- `JCODE_RUN_AUTO_POKE` (default on): when todos are left unfinished, `run` emits `{"type":"auto_poke",...}` and keeps working after `end_turn`. After a SIGINT, a resumed question ("answer only, no tools") therefore went back to counting (4→23). Set `JCODE_RUN_AUTO_POKE=0`.

## Provider
- Shapes: Anthropic Messages via `-p anthropic-api` (env `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL` **with `/v1`**, because jcode appends `/messages`). The binary also references `ANTHROPIC_AUTH_TOKEN` (not tested). It also has many OpenAI-shaped providers: `-p deepseek` (`DEEPSEEK_API_KEY`, worked with `deepseek-chat`), `-p openai-api`, and `-p openai-compatible`, which wants `OPENAI_COMPAT_API_KEY` + `JCODE_OPENAI_COMPAT_API_BASE` (failed: I only set `OPENAI_API_KEY`).
- Swapping providers on the Anthropic shape: DeepSeek's `/anthropic/v1` works only with no `-m`. jcode then sends its default Claude model, which DeepSeek maps to its own model. `deepseek-chat` is rejected locally.
- No login step. The env key is enough (`auth_method: api_key`). **The key is never persisted.** I scanned every HOME, the runtime dir and `/tmp/jcode-bg-tasks` for both keys: no hits. `~/.config/jcode/anthropic_model_catalog_cache.json` stores only a sha256 of the key.
- It honors `HTTPS_PROXY` and `NO_PROXY`. I checked this with a logging CONNECT proxy, and TLS through the machine's agent proxy works.
- Other hosts, all of which fail silently when denied (runs still exit 0):
  - `telemetry.jcode.sh` (about 20 CONNECTs per run): turned off by `JCODE_NO_TELEMETRY=1`.
  - `api.github.com` (update check): turned off by `--no-update`.
  - `models.dev` (pricing, after the answer): always fetched; no switch found.
  - **`api.anthropic.com` (`/v1/models` catalog, hard-coded URL)**: fetched even when `ANTHROPIC_BASE_URL` points at DeepSeek. So with a non-Anthropic provider, that provider's key is sent to api.anthropic.com unless the proxy blocks it (the sandbox proxy does).

## Artifacts it loads
- `~/.jcode/config.toml`: `[hooks]`, `[tools]`, `[provider]`, `[providers.<name>]`, `[safety]`, `[agents]`. `JCODE_HOME` overrides `~/.jcode`.
- Hooks: `[hooks] turn_start/turn_end/session_start/session_end/pre_tool/post_tool/post_tool_feedback/pre_tool_transform`. Env overrides: `JCODE_HOOK_*` (from the embedded docs/HOOKS.md; not tested).
- Skills: `~/.jcode/skills/<name>/SKILL.md` (frontmatter `name`, `description`) and workspace `./.jcode/skills/<name>/SKILL.md`. **Both were tested and both loaded** (PURPLE-91 / ORANGE-33). The binary also mentions importing `.claude/skills` and `.codex/skills` (not tested).
- MCP: `~/.jcode/mcp.json`, workspace `.jcode/mcp.json`, `.claude/mcp.json`, `.mcp.json` (`mcpServers`; not tested).
- It also reads other CLIs' credentials if present (`~/.claude/.credentials.json`, `~/.codex/…`, `~/.pi/agent/auth.json`). A fresh HOME has none.

## Outputs
- `run --ndjson`: `start{session_id,model,provider}` is **line 1, before any network call**. Then `connection_type`, `connection_phase{phase}`, `text_delta{text}`, `tool_start{id,name}`, `tool_input{delta}`, `tool_exec`, `tool_done{id,name,output,error}`, `message_end{stop_reason}`, `tokens{input,output,cache_read_input,cache_creation_input}` (one per API call), `auto_poke`, then `done{text,session_id,usage{input_tokens,output_tokens,cache_read_input_tokens,cache_creation_input_tokens},model,provider}` or `error{message,session_id}`.
- `run --json` prints a single object at the end: `{session_id,provider,model,text,usage}`.
- **No cost field anywhere.** Exit codes: 0 on success; 1 for a bad key (401 → `error` event), an unknown model or a missing session. SIGINT kills the process by signal (rc −2, i.e. 130 in the shell) with no `done` event.
- Bridge (NDJSON frames `{"v":1,"ev":...,"reply_to"?}`): `hello_ok`, `attached{session}`, `message_accepted`, `connection_phase`, `reasoning_delta/done`, `text_delta`, `text_done`, `text_replace`, `tool_start`, `tool_input_delta`, `tool_exec`, `tool_done`, `token_usage`, `soft_interrupt_injected{client_ids,point}`, `turn_stopped{reason}`, `turn_done`, `session_status`, `runtime_info`, `model_info`, `error{code,message}`.

## State it keeps
- `~/.jcode/sessions/<id>.json` + `.bak` (run mode also writes `.journal.jsonl`), `~/.jcode/logs/jcode-YYYY-MM-DD.log`, `session-metadata-v1.sqlite3`, `model-usage-v1.sqlite3`, `cache/models_dev_pricing.json`, `telemetry_*` (even with telemetry off: id, lock), `~/.config/jcode/anthropic_model_catalog_cache.json`.
- Outside HOME: `/tmp/jcode-bg-tasks/<task>.output|status.json` (background tools) and the daemon runtime dir (sockets, `durable-state/`).
- **Nothing is written into the workspace** beyond what the model does.

## Continue
- `jcode run --ndjson -p anthropic-api --resume <session_id> "<text>"`. Run 1, "Remember the word ORCHID. Reply OK." → "OK". Run 2, resumed → "The word you asked me to remember is **ORCHID**." Same session id both times.
- Bridge: `attach_session{session_id}` resumes any saved session, also in a freshly started daemon.

## Mid-turn steering
- Protocol: `jcode api-bridge --stdio --no-update -p anthropic-api -m <model>`, JSON lines on stdin and stdout (harness API v1, the same as `@1jehuang/jcode-sdk` protocol.d.ts). Each frame is `{"v":1,"id":N,"req":...}`:
  - `{"req":"hello","client":"hi","min_version":1,"max_version":1}`
  - `{"req":"create_session","working_dir":WS}` (or `attach_session`) → `attached.session.session_id`
  - optional `set_model`
  - `{"req":"send_message","session_id":S,"content":TASK}`
  - while it works: `{"req":"soft_interrupt","session_id":S,"content":TEXT,"client_id":"u1"}` (`urgent:true` may skip queued tools at point C). The text is injected at the next safe point (D after tools, B after text-only). The docs say a soft interrupt sent while idle starts a new turn (`point:"turn_start"`); not tested.
- Result: PASS. Steer sent at 40.98 s with count=3. One more in-flight `sleep 1` ran, then `soft_interrupt_injected point D` at 43.42 s and `turn_done` at 51.15 s. count.txt = 1,2,3 and done.txt = DONE.
- The bridge starts a **separate daemon** (`jcode serve`, its own process group, inherits the bridge's env/HOME/cwd, survives the bridge). Without `XDG_RUNTIME_DIR`, the bridge dialed `/tmp/jcode-user/jcode.sock` while the daemon bound `/tmp/jcode-0/` → `connect legacy socket` error, exit 1. **Set `JCODE_RUNTIME_DIR`** (e.g. `/tmp/jcode-rt`, mode 700).

## Graceful stop
- `run` + SIGINT to the process group: exited 0.3 s after the signal, rc −2 (by signal), no `done` event. The session was saved (dangling tool_use patched as "Tool output missing (session interrupted…)"). Resumed with `JCODE_RUN_AUTO_POKE=0`: "I was writing the numbers 1 to 30 … I had gotten through **3**" → PASS.
- Bridge `{"req":"cancel","session_id":S}`: `turn_stopped{reason:"interrupted"}` + `turn_done` came within 0.1 s, and the session is idle/saved. Reattached in the same daemon: "I got through **3**" → PASS.
- **However, cancel does not kill a running bash tool:** a single `for … sleep 1` loop kept counting 3→21. It only died when `jcode server stop --force` ran (SIGTERM to the daemon, 1.7 s). Plain `server stop` refuses without `--force`.
- Closing the bridge's stdin or SIGINT to the bridge: the bridge exits at once (0 / −2). The daemon marks the session `Crashed: Client disconnected while processing` and moves the running tool to a background task, which **keeps running** (count reached 30). The session is still resumable: a new daemon plus `attach_session` → "got as far as writing **3**".

## Worst case
Not needed: both run-mode resume and bridge reattach work. As a fallback, `~/.jcode/sessions/<id>.json` (`messages[]`) could be handed back as a transcript.

## The folder we should ship
- harness.json: provider `anthropic`. `files: {"AGENTS.md":"{instructions}"}`. `run.env`: `HOME={workspace}/.home`, `JCODE_NO_TELEMETRY=1`, `JCODE_RUN_AUTO_POKE=0`, `JCODE_RUNTIME_DIR=/tmp/jcode-rt`. `run.stdout`: `application/x-ndjson`. `run.interrupt`: `steered`.
- run.sh:
  - Export `ANTHROPIC_BASE_URL="${base%/v1}/v1"` and `ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"`.
  - `mkdir -m700 -p /tmp/jcode-rt`.
  - `exec python3 adapter.py`. adapter.py starts `jcode api-bridge --stdio --no-update -p anthropic-api ${HI_MODEL:+-m "$HI_MODEL"}` (process group), then:
    1. Send `hello`, then `attach_session(HI_RESUME)` or `create_session(working_dir=$HI_WORKSPACE)`.
    2. Write `resume` to HI_OUTPUT immediately.
    3. Send `send_message(HI_TASK)`.
    4. Each later stdin line (a JSON string) becomes `soft_interrupt{content, client_id}`.
    5. On SIGINT or end of stdin: send `cancel`, wait for `turn_done`, close the bridge, then `jcode server stop --force` (same env) to kill orphaned tools.
    6. On `turn_done` (no pending soft interrupts): stop the same way.
  - A non-steered fallback: `jcode run --ndjson --no-update -p anthropic-api [-m M | --resume ID] "$HI_TASK"`, where -m is pointless on resume.
- report.py: pass the frames through, flushed.
  - `resume` = `attached.session.session_id`, or `start.session_id` in run mode; write it at once.
  - `answer` = `text_delta` concatenated since the last user message (honor `text_replace`), or `done.text`.
  - `usage` = sum of `token_usage`, or `done.usage`.
  - `status`: ok on `turn_done`/`done`; interrupted on `turn_stopped.reason=interrupted` or a signal; fail on `error` or `turn_stopped` failure.
  - `cost_usd`: null (never reported).
- artifacts: `config.toml` → `.jcode/config.toml` (hooks/tools/providers); `<skill>.md` → `.jcode/skills/<name>/SKILL.md`; `mcp.json` → `.jcode/mcp.json`; overlay → `.jcode/prompt-overlay.md`.
- changes from today's folder:
  - It reads `HI_SESSION_ID` and writes `session_id`; the contract is `HI_RESUME` / `resume`, written early.
  - It uses `--json`, which emits nothing until the end; use `--ndjson` or the bridge.
  - Missing: `--no-update`, `JCODE_RUN_AUTO_POKE=0`, any `run.interrupt`, and an `error`-event → fail mapping.
  - Its comment "refuses -m on resume" is wrong: -m is silently ignored.
  - The `claude-sonnet-4-5` fallback is fine; no cost is available.

## Evidence
- All runs used a fresh HOME and workspace and a logging CONNECT proxy allowing only provider hosts. Model claude-sonnet-4-6.
- `run --ndjson "Say hello in 3 words."`: exit 0 in 17 s cold, 3.3 s with telemetry and update off. Events as listed under Outputs. Hosts: telemetry.jcode.sh ×20, api.anthropic.com ×2, api.github.com, models.dev; only api.anthropic.com ×2 and models.dev remained with `JCODE_NO_TELEMETRY=1 --no-update`.
- AGENTS.md "ZEBRA-42" was followed; CLAUDE.md "LLAMA-77" was ignored.
- ORCHID: run 1 "OK", run 2 `--resume` "…**ORCHID**". `-m claude-haiku-4-5` on resume: exit 1 (unknown alias); `-m claude-haiku-4-5-20251001`: ignored, sonnet answered.
- DeepSeek: `-p anthropic-api` + `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic/v1`, no -m: exit 0, its default Claude model, then CONNECT api.anthropic.com. With `-m deepseek-chat`: exit 1. `-p deepseek -m deepseek-chat`: exit 0.
- Bad key: `error` event (401 invalid x-api-key), exit 1, 1.3 s.
- SIGINT to `run` at count=3: rc −2 after 0.3 s, count 3. Resume (auto-poke on): correct answer, then auto_poke and counting to 23 (killed at 120 s). With `JCODE_RUN_AUTO_POKE=0`: "gotten through **3**", end_turn, `done`, exit 0, 4.5 s.
- Bridge:
  - `hello_ok` capabilities include `soft_interrupt_ids`.
  - Steer test: PASS (above).
  - `cancel` at count=3: `turn_stopped interrupted` after 0.1 s, count stayed 3; reattach recall PASS.
  - One-command loop + `cancel`: count kept rising 6→15 until `server stop --force`.
  - stdin EOF mid-turn: bridge exit 0, session Crashed, count frozen at 3 (per-number commands).
  - SIGINT to the bridge: exit −2; the backgrounded loop finished 30; `/tmp/jcode-bg-tasks/*.status.json` shows completed.
- Cleanup: daemon stopped; runtime dir, `/tmp/jcode-bg-tasks`, HOMEs and the downloaded SDK deleted; work dir is 468 KB.
