# Pi — pi 1.3.0 (pin: @earendil-works/pi-coding-agent@1.3.0)

**Verdict:** works. It runs headless in json and RPC modes. models.json points it at any base URL that speaks the Anthropic or OpenAI API shapes. It honors HTTPS_PROXY, and with PI_OFFLINE=1 it contacts only the provider's host.
**Tier:** steered. Tested with the candidate folder (`work/pi/folder`): `pi --mode rpc` plus adapter.py. A steer sent after 3 numbers produced done.txt=DONE, counting stopped at 3, and the run exited 6.2 s later. A SIGINT or end-of-stdin abort exits 0 in 0.1 s, and a resumed run names "3".

## Inputs
- Task: a positional argument (`pi -p [--mode json] "<task>"`), or with `--mode rpc` a `{"type":"prompt","message":...}` record on stdin (RPC mode rejects `@file` arguments). It never asks for approval because it has no permission system; `--tools` and `--exclude-tools` only restrict tools.
- Model: `--provider <name> --model <id>` or `--model provider/id`. Thinking is set with a `:<level>` suffix or `--thinking off..max` (default medium). An id missing from the catalog is used as given, with the stderr line "Warning: ... Using custom model id."
- Working dir: the cwd (there is no flag). Context files: `AGENTS.md`, `CLAUDE.md` and `AGENTS.override.md` from the cwd and its parents, plus `~/.pi/agent/AGENTS.md`. `--no-context-files` turns them off. The model follows them: with an AGENTS.md rule "end every reply with PINEAPPLE", every reply ended with PINEAPPLE.
- System prompt: `--system-prompt`, `--append-system-prompt <text|file>`, and `~/.pi/agent/SYSTEM.md` / `APPEND_SYSTEM.md` (verified loaded).
- Project trust: `.pi/*` and the project's `.agents/skills` load only with `--approve` (or `defaultProjectTrust:"always"` in ~/.pi/agent/settings.json). In -p, json and rpc modes they are skipped silently by default. AGENTS.md needs no trust.

## Provider
- API shapes: `anthropic-messages`, `openai-completions` and `openai-responses`, plus google, bedrock, azure and many built-in providers. The key comes from each provider's env var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`...) or from `--api-key`, which shows up in argv, so avoid it.
- Base URL: there is no env var for anthropic or openai. Set it in `$HOME/.pi/agent/models.json` (`PI_CODING_AGENT_DIR` moves that directory):
  - Override a built-in provider: `{"providers":{"anthropic":{"baseUrl":"https://host"}}}`. Catalog prices and limits stay, and the key still comes from `ANTHROPIC_API_KEY`. Tested with DeepSeek: `https://api.deepseek.com/anthropic` plus `--provider anthropic --model deepseek-chat` made a tool call and answered.
  - Add a custom provider: `{"providers":{"hi":{"baseUrl":URL,"api":"openai-completions","apiKey":"$HI_PROVIDER_KEY","models":[{"id":"deepseek-chat"}]}}}`, then `--model hi/deepseek-chat`. Tested OK against DeepSeek for openai-completions and anthropic-messages.
  - `apiKey` and header values expand `$VAR`, `${VAR}` and `!cmd`, so the key never touches disk. `baseUrl` does NOT expand: `$HI_PROVIDER_URL` gives "Invalid URL", so write the URL literally.
- Request paths (seen by a recorder): anthropic → `<base>/v1/messages?beta=true` (base WITHOUT /v1, header x-api-key). openai-completions → `<base>/chat/completions` and openai-responses → `<base>/responses` (base WITH /v1, Bearer auth).
- There is no login step. The key is never persisted: `auth.json` is written as `{}`, and after all runs no file under HOME or the workspace contained a key.
- HTTPS_PROXY: honored. Every call showed up as a CONNECT on my logging proxy. pi also respects NO_PROXY; this machine's NO_PROXY lists api.anthropic.com, so strip it when testing. There is also an `httpProxy` setting.
- Startup traffic: `-p` mode contacts only the provider host. `--mode rpc` makes about 10 CONNECTs to `pi.dev:443` (catalog, version check, telemetry). An allowlist proxy denied them and the run was unaffected. `PI_OFFLINE=1` (same as `--offline`) removes all of them (verified). `PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0` on their own do not.
- Cost: priced from the catalog. Custom models report 0 (add a `"cost"` per model). An unknown id under a built-in provider gets a fallback price: deepseek-chat was billed at about $5/M input. Don't trust the cost for models outside the catalog.

## Artifacts it loads
All under `$HOME/.pi/agent/`. Each was verified in the system prompt sections or by its effect, except where noted:
- `settings.json`, `models.json`, `mcp.json` (`{"mcpServers":{...}}`, not tested live), `keybindings.json`
- `AGENTS.md` (global instructions), `SYSTEM.md`, `APPEND_SYSTEM.md`
- `skills/<name>/SKILL.md` (Agent Skills format) and `$HOME/.agents/skills/<name>/SKILL.md`. Both appear in the system prompt.
- `prompts/<name>.md` → `/<name> args` in the task. Verified: `/hiprompt BANANA` expanded, with `$1` substituted.
- `extensions/*.ts`: TypeScript, loaded without a build step. Its event bus is pi's hook API: a `pi.on("tool_call",...)` handler fired (verified).
- Workspace equivalents under `.pi/` (settings, mcp.json, skills, prompts, extensions, SYSTEM.md, APPEND_SYSTEM.md) and `.agents/skills` need `--approve`.

## Outputs
- Modes: `--mode text` (answer only; exit 1 plus stderr on a provider error), `--mode json` (NDJSON), `--mode rpc` (NDJSON events plus `response` records).
- Resume id: in json mode, line 1 is `{"type":"session","version":3,"id":"<id>",...}` at about 0.4 s, before any model call. RPC mode emits no `session` event. Either send `{"type":"get_state"}` and read `response.data.sessionId`/`sessionFile` (0.4 s), or choose the id yourself with `--session-id`.
- Events: agent_start, turn_start/turn_end, message_start/message_update/message_end (roles system, user, assistant, toolResult), tool_execution_start/update/end, queue_update, compaction_*, auto_retry_*, agent_end, agent_settled{aborted}. The run is done at `agent_settled`.
- Assistant `message_end.message` holds `content[]` (text/thinking/toolCall), `stopReason` (stop|toolUse|error|aborted), `errorMessage`, and `usage{input,output,cacheRead,cacheWrite,totalTokens,reasoning,cost{...,total}}`. Usage is per message and must be summed.
- Exit codes: json and rpc modes exit 0 even when the provider returns 400 or 404; only stopReason:error shows the failure. Text mode exits 1.

## State it keeps
- Sessions: `$HOME/.pi/agent/sessions/--<cwd, / replaced by ->--/<iso>_<id>.jsonl`. `--session-dir` or `PI_CODING_AGENT_SESSION_DIR` moves them. pi also keeps `models-store.json` (a 244 KB copy of the catalog), `auth.json` ({}), `trust.json` and `mcp.log` there.
- It writes nothing into the workspace (verified from directory listings).

## Continue
- `--session-id <id>` takes an exact id: it creates the session if missing (with a stderr warning) and resumes it if present. This only finds sessions whose recorded cwd equals the current cwd, even with `--session-dir`.
- `--session <file path>` resumes from any cwd (tested). `--session <id>` from another cwd prints "Session found in different project" and does nothing. `-c` continues the latest session in this cwd.
- ORCHID test:
  - Run 1, `--session-id hi-orchid-1 "Remember the word ORCHID. Reply OK."` → "OK."
  - Run 2, same id → "The word you asked me to remember is **ORCHID**."
  - Run 3, `-c` → "orchid"

## Mid-turn steering
- RPC: send `{"type":"steer","message":"..."}` or `{"type":"prompt","message":"...","streamingBehavior":"steer"}`. The response has `disposition:"queued"`, or `"started"` if pi was idle. The message is delivered after the running tool calls finish, before the next LLM call. `follow_up` queues a message for after the run. A plain `prompt` while pi is streaming, without streamingBehavior, is an error.
- Test (adapter, sonnet-4-6): the steer line went in at 13.8 s with n=3 and was queued. One `sleep 1` already in flight finished, the user message was injected at 16.2 s, `echo DONE > done.txt` ran at 18.1 s and the run settled at 20.0 s. The count stayed at 3. Pass.

## Graceful stop
- RPC `{"type":"abort"}` produces, all within 10 ms: an assistant message with stopReason `aborted` (or `error` "This operation was aborted" if a bash tool was running; the tool's process is killed), `agent_settled{aborted:true}`, then the abort response. Queued steers carry on after an abort unless `clear_queue` is sent first. Closing stdin gives an orderly exit 0.
- Through the adapter: killpg SIGINT at n=3 → exit 0 after 0.1 s, the count stayed at 3 and the session was saved. The resumed run said "...got as far as **3** before the command was aborted." Pass. End of stdin behaves the same, 0.1 s.
- Plain `-p --mode json` plus SIGINT (earlier run, exp_d_pi.py): pi dies with rc -2 and no final event. The session file already holds every finished message, though, and a resumed run answers with the count, so the `continued` tier would also work.

## Worst case
Not needed. If resume ever fails, the session `.jsonl` (one message per line) under `$HOME/.pi/agent/sessions` is the transcript to hand back.

## The folder we should ship
(Tested candidate: `work/pi/folder/{run.sh,adapter.py,report.py}`.)
- harness.json: provider `anthropic` (https://api.anthropic.com); `files: {"AGENTS.md": "{instructions}"}`; `run.env: {"HOME": "{workspace}/.home"}`; `run.interrupt: "steered"`; `run.stdout: "application/x-ndjson"` (pi's RPC records passed through).
- run.sh:
  - Put the artifacts in place.
  - Merge `{"providers":{"anthropic":{"baseUrl": ${HI_PROVIDER_URL%/} with any trailing /v1 removed}}}` into `$HOME/.pi/agent/models.json`, keeping any models.json the user supplied.
  - `export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY" PI_OFFLINE=1 PI_TELEMETRY=0`, then `exec python3 adapter.py`.
- adapter.py:
  - Session id: HI_RESUME or HI_SESSION_ID, else a new uuid. If `$HOME/.pi/agent/sessions/*/*_<id>.jsonl` exists, pass `--session <that file>` (works whatever the cwd); otherwise pass `--session-id <id>`.
  - Start `pi --mode rpc --provider anthropic --model ${HI_MODEL:-claude-sonnet-4-6}` with `start_new_session=True`, so the server's SIGINT reaches only the adapter.
  - Send get_state, then prompt(HI_TASK).
  - Read stdin: skip the request JSON (it may be pretty-printed, so accumulate lines until it parses). Turn each later line into `{"type":"prompt","message":<str>,"streamingBehavior":"steer"}`.
  - On SIGINT, SIGTERM or end of stdin: send `clear_queue`, then `abort`.
  - Exit at `agent_settled` when no steer is pending, then close pi's stdin.
- report.py:
  - resume: the chosen id, written to HI_OUTPUT before pi starts (it also appears in the `session` event and get_state).
  - answer: the last non-empty assistant text. usage: the sum of the assistant `usage` numbers. cost_usd: the sum of `usage.cost.total`, left out when it is 0.
  - status: fail if the last assistant stopReason is `error`; ok if `agent_settled.aborted`.
  - Rewrite HI_OUTPUT at every agent_settled.
- artifacts (what users drop in, and where it goes under $HOME):
  - settings → `.pi/agent/settings.json`
  - skills → `.pi/agent/skills/<n>/SKILL.md` (or `.agents/skills/<n>/SKILL.md`)
  - prompt templates → `.pi/agent/prompts/<n>.md`
  - extensions and hooks → `.pi/agent/extensions/<n>.ts`
  - MCP → `.pi/agent/mcp.json`
  - global rules → `.pi/agent/AGENTS.md`
  - system prompt → `.pi/agent/SYSTEM.md` or `APPEND_SYSTEM.md`
- changes from today's folder:
  1. HI_PROVIDER_URL is ignored, so the base URL is never set: no non-Anthropic provider can work.
  2. report.py writes `session_id` only at the end, not early, and takes usage and cost from the last message only; they must be summed.
  3. Status ignores aborts, and because json mode exits 0 on provider errors, the reported status is the only failure signal.
  4. PI_OFFLINE is not set (needed to stop the pi.dev calls when switching to rpc).
  5. `--session-id` breaks if the workspace path changes between runs; look up the session file instead.
  6. There is no `run.interrupt` and no adapter.
  7. Contract naming: the code uses HI_SESSION_ID/`session_id`, the brief says HI_RESUME/`resume`. The candidate reads both and writes both.

## Evidence
- smoke: `pi -p --mode json --provider anthropic --model claude-sonnet-4-6 "Reply with just OK"` through the logging CONNECT proxy with NO_PROXY stripped → rc 0 in 5.2 s, one CONNECT to api.anthropic.com:443. Events: session, agent_start, message_end×3, turn_end, agent_end, agent_settled.
- recorder (127.0.0.1) as the anthropic baseUrl → `POST /v1/messages?beta=true` with x-api-key. json mode rc 0 with stopReason error; text mode rc 1. Custom providers → `/v1/chat/completions` and `/v1/responses`. A `$HI_PROVIDER_URL` baseUrl → "Invalid URL".
- DeepSeek through an allowlist proxy (only api.deepseek.com): hi-chat/deepseek-chat, hi-anth/deepseek-chat and the anthropic override with deepseek-chat each ran `echo` and answered. Only api.deepseek.com was contacted.
- rpc under an allowlist of api.anthropic.com: 10 denied pi.dev CONNECTs, run OK. With PI_OFFLINE=1: no pi.dev calls.
- artifacts run: the system prompt sections (preamble, tools, rules, docs, addendum, project_context, skills, cwd) contained the global AGENTS.md, APPEND_SYSTEM.md, the user skill, the ~/.agents skill and the workspace AGENTS.md. The project .pi skill loaded only with `--approve`. The extension's tool_call hook logged "tool_call bash".
- Continue: ORCHID via `--session-id` and `-c` (above). `--session-dir` plus a different cwd → a new session (fail). `--session <file>` from another cwd → ORCHID.
- Adapter runs, in a server-like setup (HOME=ws/.home, allowlist proxy, request JSON with indent=2 on stdin, SIGINT via killpg):
  - steer → n=3, done.txt=DONE, rc 0.
  - sigint → rc 0 in 0.1 s, n=3; output.json had the resume id from the start.
  - resumed "ask" → "got as far as **3**".
  - eof → rc 0 in 0.1 s, n=3.
