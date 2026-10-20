# Claude Code — claude 2.1.304 and 2.1.42 (pin: @anthropic-ai/claude-code@2.1.42; recommend 2.1.304)

**Verdict:** works with caveats. Both versions run headless, swap providers, load every artifact type and steer mid-turn. 2.1.42 ignores AGENTS.md (which today's folder writes), and its resume only works from the same cwd.
**Tier:** steered. A prototype adapter.py on both versions: the steer after 3 numbers gave done.txt=DONE, count stopped at 3, and the adapter exited by itself after one `result`. EOF or SIGINT stopped the run in 0.2–1.6 s, and a resumed run named "count.txt … got through 2/3".

## Inputs
- Task: `-p "<text>"` (argument). For steering: `-p --input-format stream-json`, and stdin lines `{"type":"user","message":{"role":"user","content":"<text>"},"parent_tool_use_id":null}`.
- Headless: `-p` skips the trust dialog. Never asks: `--dangerously-skip-permissions` (init shows `permissionMode:"bypassPermissions"`). Running as root needs env `IS_SANDBOX=1`.
- Model: `--model <id>`. No cwd flag: it uses the process cwd (`--add-dir` adds more directories).
- Instruction files (each one tested by asking for a code word only that file held):
  - workspace `CLAUDE.md`: both versions follow it.
  - workspace `AGENTS.md`: **2.1.42 ignores it** (cli.js does not contain the string). 2.1.304 reads it only when the project has no CLAUDE.md (`instructionFiles` default "claude-md-or-agents-md").
  - `$HOME/.claude/CLAUDE.md` and `$HOME/.claude/rules/*.md`: both versions follow them.
  - `--append-system-prompt <text>` is another route that leaves the workspace alone (not tested).

## Provider
- Speaks the Anthropic Messages API only. Config: `ANTHROPIC_BASE_URL` (no `/v1`; it appends `/v1/messages`), plus `ANTHROPIC_API_KEY` (x-api-key) and/or `ANTHROPIC_AUTH_TOKEN` (Bearer). Here, key-only, token-only and both all worked against api.anthropic.com. No login step.
- DeepSeek works on both versions: `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`, `--model deepseek-chat`, egress limited to api.deepseek.com.
  - 2.1.304 prints `[claude-code:unrecognized_model]` on stderr and emits many `system/thinking_tokens` events.
  - `total_cost_usd` is priced with Claude's price table, so it is wrong for other providers.
  - 2.1.42 also sends background calls on `claude-haiku-4-5` (it appears in `modelUsage`). With another provider, set `ANTHROPIC_SMALL_FAST_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL` to `HI_MODEL` (the env names exist in both builds; this was not tested).
- Honors `HTTPS_PROXY` (CONNECT). It works with **no DNS at all**: I tested it in a mount namespace with an empty hosts file and a dead nameserver, with and without `CLAUDE_CODE_PROXY_RESOLVES_HOSTS`.
- Startup traffic (logged by a CONNECT proxy):
  - Without `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`: `http-intake.logs.us5.datadoghq.com` (telemetry), plus extra api.anthropic.com calls (policy-limits, remote-settings).
  - With it: 2.1.304 contacts only the provider host. 2.1.42 still makes 2 CONNECTs to api.anthropic.com. Under DeepSeek those were denied and did no harm: rc 0, 5.5 s.
- Key persistence: none. A scan of every HOME and workspace for the full key or its last 20 chars found nothing, `.claude.json` included.

## Artifacts it loads
Paths under `$HOME` (`CLAUDE_CONFIG_DIR` overrides `~/.claude`). Every item was confirmed by the init event or by the model's answer, on both versions unless noted.
- `.claude/settings.json`: `hooks` work. SessionStart, PreToolUse(matcher Bash) and Stop all fired. `env` works (`SURVEY_ENV` was visible to Bash). **`mcpServers` here is ignored.**
- MCP:
  - user scope: `.claude.json` `{"mcpServers":{...}}` loads (`source:user`). The CLI rewrites this file every run but keeps the key.
  - `--mcp-config <file>` loads (`source:dynamic`).
  - workspace `.mcp.json` loads **without approval** in `-p` (`source:project`).
- Skills: `.claude/skills/<n>/SKILL.md` (HOME and workspace `.claude/skills/`). Listed in `init.skills` and used by the model.
- Commands: `.claude/commands/*.md`. Agents: `.claude/agents/*.md`. Both are listed in the init event.
- Memory: `.claude/CLAUDE.md` and `.claude/rules/*.md`. Workspace: `CLAUDE.md` (and `AGENTS.md`, 2.1.304 only), `.claude/settings.json`, `.claude/skills`, `.mcp.json`.
- 2.1.304 also turns on "auto memory" at `$HOME/.claude/projects/<slug>/memory/` (in `init.memory_paths`). `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` exists; not tested.

## Outputs
- `--output-format text|json|stream-json`. stream-json needs `--verbose`. NDJSON events:
  - `system/hook_started` and `system/hook_response`: these come **before** `system/init` whenever a SessionStart hook exists, and carry session_id too.
  - `system/init` (tools, mcp_servers, skills, slash_commands, agents, plugins, model, claude_code_version); `assistant`; `user` (tool results; `isReplay:true` echoes with `--replay-user-messages`); `result`; `control_response` (stream-json input).
- `result` carries `subtype` (success | error_during_execution | …), `is_error`, `result` (the answer text), `session_id`, `num_turns`, `usage`, `modelUsage`, `total_cost_usd`, `duration_ms`. 2.1.304 adds `stop_reason`, `terminal_reason` and `queued_turn_count`; the last is **unreliable**: it was 0 while a message was queued.
- `usage` covers **one result** (every API call of that user turn, summed). `total_cost_usd` and `modelUsage` are cumulative: over the process on 2.1.42, and **over the whole session including earlier resumed runs** on 2.1.304 (0.1218 → 0.1294 after a 1-line resume).
- Resume id: known before launch with `--session-id <uuid>`. Otherwise it appears in the first event. In stream-json input mode, nothing is printed until the first stdin message.
- Exit codes:
  - success: 0. Bad model: 1, `result` `is_error:true`, `subtype:"success"`. Unknown `--resume`: 1, `No conversation found…` on stderr.
  - reusing an existing `--session-id`: 1, `Session ID … is already in use.`
  - `--resume` together with `--session-id` without `--fork-session`: 1.
  - after a control interrupt and stdin close: 0 on 2.1.42, 1 on 2.1.304.

## State it keeps
- `$HOME/.claude/projects/<cwd with / and . → ->/<session>.jsonl` (transcript) and `$HOME/.claude.json` (+ backups: 2.1.42 next to it, 2.1.304 in `.claude/backups/`).
- Also under `$HOME/.claude/`: `policy-limits.json`, `session-env/`, `shell-snapshots/`.
  - 2.1.42 only: `debug/<id>.txt` (written by default) and `todos/`. It also runs `npm root --global` locally, which writes `$HOME/.npm/_logs/`.
  - 2.1.304 only: `remote-settings.json`, `sessions/`, `.last-cleanup`.
- Outside HOME: `/tmp/claude-<uid>/<cwd-slug>/tasks/` (Bash output files). Nothing is written into the workspace.

## Continue
- `--resume <id>` (or `-c` for the latest in this cwd). With `--session-id <uuid>` on the first run, then `--resume <uuid>`: "Remember ORCHID" → "ORCHID", on both versions. The session id stays the same.
- **2.1.42 resolves the session by cwd**: run from another dir it fails with `No conversation found`. 2.1.304 finds it from any cwd. So the workspace path must stay the same across runs on 2.1.42.
- On 2.1.42 a steer's text is not saved for resume; 2.1.304 saves it (prior finding, validate/claude-pi).

## Mid-turn steering
- Protocol: `claude -p --input-format stream-json --output-format stream-json --verbose --replay-user-messages`. Each stdin line is a user message (shape above).
- When the steer arrives during a tool loop, it merges into the running turn: 5 turns, **one** `result`.
- When it arrives while the model writes a tool-less final answer, it runs as a **new turn**: `result`, `system/init`, the replay, a second `result`.
- **Done condition (tested on both):** a `result` arrives and the number of `isReplay` user events ≥ the number of messages sent. Then close the CLI's stdin and it exits.
- Interrupt: `{"type":"control_request","request_id":"x","request":{"subtype":"interrupt"}}` gives a `control_response`, then `result/error_during_execution` within ~30 ms.

## Graceful stop
- Plain `-p` + SIGINT to the process group (prior finding): 2.1.42 exits 0 with **no** `result`; 2.1.304 emits `result/error_during_execution`, exit 0. Both resumable ("got through 2").
- Through the adapter, run in its own session so SIGINT reaches only the adapter, which sends `interrupt`:
  - 2.1.304 exits in ~1.5 s.
  - 2.1.42: in one run the model had used Bash `run_in_background`. The interrupt did **not** kill that background command; it counted to 30, a `<task-notification>` turn ran after stdin closed, and the exit came 35 s later. Fix: `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` (exists in both; not tested).
- If claude itself also receives the SIGINT: 2.1.42 exits at once without a `result`; 2.1.304 exits 0 after the interrupt result. Both still resume.

## Worst case
Not needed: every stop path left a resumable transcript. The fallback would be to hand back `$HOME/.claude/projects/*/<id>.jsonl` as context.

## The folder we should ship
- **harness.json:**
  - provider `anthropic`; `run.stdout` `application/x-ndjson`; `run.interrupt: "steered"`; `run.argv` `python3 {harness_dir}/adapter.py`.
  - `run.env`: `HOME={workspace}/.home`, `IS_SANDBOX=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_AUTOUPDATER=1`, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`.
  - `files`: `{".home/.claude/CLAUDE.md": "{instructions}"}` (user memory: both versions read it, and it is outside the user's tree), not `AGENTS.md`.
- **run.sh / adapter.py:**
  - Set the provider env: `ANTHROPIC_BASE_URL=${HI_PROVIDER_URL%/v1}`, the key in `ANTHROPIC_API_KEY` (+`ANTHROPIC_AUTH_TOKEN` for Bearer-only providers), and `ANTHROPIC_SMALL_FAST_MODEL`/`ANTHROPIC_DEFAULT_HAIKU_MODEL=$HI_MODEL` when the provider isn't Anthropic.
  - Session: `--resume $HI_RESUME`, or `--session-id $(uuidgen)` on a new conversation. Add `--mcp-config $HOME/.claude/mcp.json` if that file exists.
  - adapter.py is the prototype in work/claude-code/scripts/adapter.py:
    1. Start claude with `start_new_session=True`.
    2. Forward line 1's task and each later JSON string as a user message.
    3. Count sent vs `isReplay`; on a `result` with replays ≥ sent, close stdin.
    4. On SIGINT or EOF, send the `interrupt` control_request, then close stdin on the next `result`.
- **report.py:**
  - Pass lines through, flushed.
  - Write `resume` (the uuid) to HI_OUTPUT **at start**, since it is known before launch.
  - answer = last `result.result`.
  - status: `ok` unless `is_error`; treat `error_during_execution` after our interrupt as stopped/ok, not fail.
  - usage = sum of `result.usage` over all results.
  - cost = last `total_cost_usd`. On 2.1.304 subtract the previous run's total, saved e.g. in `$HOME/.hi-cost` per session, or the cost of resumed runs is overcounted.
  - `session_id` can come from any event; the first one is `hook_started` when hooks exist.
- **artifacts:** `settings.json → .claude/settings.json` (hooks, env, permissions); `SKILL.md → .claude/skills/<n>/SKILL.md`; `mcp.json → .claude/mcp.json` (passed with `--mcp-config`; don't overwrite `.claude.json`); `<n>.md → .claude/commands/`, `.claude/agents/`, `.claude/rules/`; `CLAUDE.md → .claude/CLAUDE.md`. MCP stdio servers need their runtime in the image, and remote MCP hosts are blocked by egress.
- **Changes from today's folder:**
  - It writes `AGENTS.md`, which 2.1.42 never reads (and it lands in the user's tree).
  - It uses `HI_SESSION_ID` (the brief: `HI_RESUME`/`resume`) and has no `--session-id` up front.
  - It writes HI_OUTPUT only at the end.
  - It has no `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (telemetry to datadoghq).
  - It has no adapter or `run.interrupt`.
  - It counts an interrupt as fail, and its cost is wrong across resumes on 2.1.304.
  - Settings `mcpServers` won't work, so ship MCP via `--mcp-config`.
- **Pin:** 2.1.304 (npm, 2026-10-19; installs the native `@anthropic-ai/claude-code-linux-x64`, ~289 MB, no node needed).
  - Over 2.1.42 it brings AGENTS.md fallback, steer text in resume, cwd-independent resume, a `result` on SIGINT, and no stray api.anthropic.com calls.
  - npm 2.1.200, 2.1.280 and 2.1.304 are native (`bin/claude.exe`); 2.1.100 is still JS (cli.js, needs node). A version ≥2 weeks old (e.g. 2.1.293, 2026-10-07) is untested.

## Evidence
Scripts and logs are in work/claude-code/{scripts,runs,e*.txt}. Model claude-sonnet-4-6 unless noted.
- e1 (both versions; NONESSENTIAL off and on):
  - `-p "Remember the word ORCHID. Reply OK." --session-id U`: init sid == U, rc 0.
  - Reusing U: rc 1. `--resume U --session-id V`: rc 1. `--resume U "Which word…"`: "ORCHID", rc 0. `--model claude-nope-1`: rc 1, is_error.
  - Hosts: loud showed datadoghq + about 30 api.anthropic.com CONNECTs on 2.1.42. Quiet: 0 hosts beyond the API.
- e2: unshare -m with fake resolv.conf and hosts (DNS fails EAI_AGAIN), proxy allowlisting only the provider.
  - Anthropic (both versions, both resolve settings) and DeepSeek `deepseek-chat`: rc 0, hi.txt written; 2.1.42 had 2 denied api.anthropic.com CONNECTs.
- e3 (HOME CLAUDE.md MANGO, rules LIME, skill ZEBRA-42, workspace skill OTTER-7, AGENTS KIWI, workspace CLAUDE.md FIG; MCP from .claude.json, settings.json, .mcp.json and --mcp-config):
  - 42: MANGO, UNKNOWN (AGENTS), FIG, LIME, ZEBRA-42, OTTER-7, MCP userjson/projectjson/cliflag (no settingsjson), FROMSETTINGS. hooks.log: SessionStart, PreToolUse, Stop.
  - 304: the same, except KIWI when there is no workspace CLAUDE.md, and UNKNOWN for AGENTS when there is one.
- e4 (adapter, both versions):
  - steer at 3: done.txt=DONE, count 3. Exit 0 by itself 6.5 s (42) / 5.2 s (304) after the steer; 1 result, 2 replays.
  - late message during a story: 2 results ("PINEAPPLE"). The adapter waited for the second; 304 reported `queued_turn_count=0` on the first.
  - EOF: exit in 0.22 s (42 rc 0) / 0.17 s (304 rc 1). SIGINT: 304 1.5 s; 42 35 s (background bash, counted to 30). Same-pgroup SIGINT: 0.03 s (42, no result) / 1.6 s (304).
  - Every resume answered with the counting task and 2 or 3 numbers.
- e5: `--resume` from another cwd: 42 rc 1 "No conversation found"; 304 "ORCHID". e6: `ANTHROPIC_AUTH_TOKEN` alone or with the key: OK on both.
