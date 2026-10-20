# DeepSeek Harness — dsh 0.2.0-rc.2 (pin: @deepseek-ai/dsh@0.2.0-rc.2)

**Verdict:** works with caveats — headless `--json` run, resume and SIGINT all work on DeepSeek; the model can only be set by a config patch, there is no `--model` flag; steering needs an adapter that goes through dsh's Claude-Code hook bridge.
**Tier:** steered — a PostToolUse/Stop hook (in-tree `@deepseek-ai/dsh-hooks-claude-code`, mounted by `--patch`) passed a queued stdin message to the running turn: counting stopped at 4, `done.txt`=DONE, exit 0. (`continued` also passes: SIGINT exits 130 in ≤0.12 s and the resumed run named "1, 2, 3".)

## Inputs
- Task: positional args (`dsh --profile headless --json "<task>"`) or stdin when the task is omitted or `-`. Always pass `</dev/null` when giving a positional task (`--help` hung 30 s once with stdin open).
- Headless flags: `--json`, `--session-id <id>`, `-h`. There are no other app flags: no model, cwd or approval flag. Launcher flags: `--profile <name>`, `--patch <yml>` (repeatable overlay), `--dump-config`.
- Working dir = process cwd. Model = config row `agent-default-model` {provider, model}. Shipped default: `deepseek-official`/`deepseek-flash`. Set it with a patch file passed as `--patch`:
  `- id: agent-default-model\n  config: {provider: deepseek-official, model: deepseek-chat}`. The env var `DEEPSEEK_DEFAULT_MODEL` that today's run.sh exports is **not read** (it is a constant in the source).
- Permissions: `DSH_PERMISSION_MODE` = `read-only` | `workspace-write` (default; approval `ask`) | `danger-full-access` (approval `never`). Headless has no approval answerer, so per its docs an `ask` resolves `unavailable` and the action is refused ("fails closed"), not a hang (not tested). Use `danger-full-access`: the container is the sandbox, and dsh's own sandbox (bwrap, then Landlock) can't be relied on in a no-capabilities container.
- Instructions: `AGENTS.md` and `CLAUDE.md` (and `*.local.md`) on the chain from the project root (`.git`) down to cwd, plus global `$HOME/.dsh/AGENTS.md`. The model follows them: an AGENTS.md rule saying "end with ZEBRA-42" was obeyed.

## Provider
- Shape: **Anthropic Messages** (POST `<base>/v1/messages`, headers `x-api-key` and `anthropic-version: 2023-06-01`). It does **not** speak OpenAI chat, so the description in today's harness.json is wrong.
- Env vars: `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com/anthropic`; `/v1` is appended unless the URL already ends in `/v1`) and `DEEPSEEK_API_KEY` (the env value wins over stored credentials). `https://api.deepseek.com/anthropic` and `/anthropic/v1` both work. `https://api.deepseek.com` and `https://api.deepseek.com/v1` give `HTTP_404` (exit 1).
- No login step. Honors `HTTPS_PROXY` (launcher-installed dispatcher). With `DSH_TELEMETRY_DISABLED=1`, a logging CONNECT proxy saw only `api.deepseek.com:443` (2 connections per run: the turn plus a title request).
- Telemetry: the OTLP row (`https://dsh-otel-collector.deepseeksvc.com/v1/logs`, mode `FEEDBACK_ONLY`) is hard-disabled by any non-empty `DSH_TELEMETRY_DISABLED`.
- Extra data sent to the provider: `session-log-deepseek` adds a top-level `dsh_session_log` field (an incremental copy of the session log) to requests, and a user id from `$HOME/.dsh/.anonymous-user-id`. The source shows no check on the host. For a non-DeepSeek Anthropic-shape provider, disable these rows by patch (`- id: session-log-deepseek\n  disabled: true`); whether api.anthropic.com accepts the extra field is not tested (using the Anthropic key here was refused by my permission layer).
- Key persistence: none. Scanned all files and the decompressed session logs: the key is absent.

## Artifacts it loads
- Config layers: shipped bundles → `$HOME/.dsh/profiles/headless/cordis.patch.yml` → `$HOME/.dsh/cordis.patch.yml` (home-level) → `--patch` files. `DSH_HOME` overrides `~/.dsh`. The profile is auto-created on first run (`profiles/headless/{cordis.yml,cordis.patch.yml,package.json,pnpm-workspace.yaml}`).
- Skills: `<project>/.dsh/skills`, `<project>/.agents/skills`, `$HOME/.dsh/skills`, `$HOME/.agents/skills` (`DSH_AGENTS_HOME`). Format: `<name>/SKILL.md` or flat `<name>.md`, with frontmatter `name` and `description`.
- MCP: not mounted by default. Add rows `name: '@deepseek-ai/dsh-mcp-client'` with config `{serverName, transport: stdio|streamable-http, command/args/env | url/headers}` in a patch.
- Hooks: Claude Code `hooks.json` or settings format, via the row `@deepseek-ai/dsh-hooks-claude-code` (config `configPath` absolute). Events: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop, SubagentStart/Stop. A Codex-format bridge `dsh-hooks-codex` is also shipped.

## Outputs
- `--json`: NDJSON on stdout. Event types: `session` {sessionId, cwd} (**always line 1, before any model call**), `status` {phase: turn_start|step_start|step_end (+usage{inputTokens,outputTokens,cacheReadTokens,cacheWriteTokens,totalTokens})|turn_end (+reason{kind: completed|aborted|error, error{message,code,status}})}, `thinking`, `text`, `tool_call` {callId,tool,input}, `tool_result` {callId,status,result}, `final` {text}, `error` {message}. Event strings are capped at 8 KiB; `final` is not capped. Text arrives per committed step, not per token.
- Without `--json`: final answer on stdout, reasoning on stderr. stderr always gets `dsh: <code>: <message>` on failure.
- Exit: 0 when the turn completed. 1 on error, abort or an unknown or mismatched `--session-id` (an `error` event, no `final`). An in-turn failure still prints `final` "", with `turn_end.reason.kind=error`. SIGINT gives **130**, prints `final` "" and **no** `turn_end`.
- No cost field anywhere. Usage must be summed over `step_end`.

## State it keeps
- `$HOME/.dsh/sessions/<cwd-slug>/<session-id>/session.v4.jsonl.zstd` (multi-frame zstd JSONL) plus `session.lock`; `$HOME/.dsh/storages/session_projcache/sessions/<id>.json`; `$HOME/.dsh/.anonymous-user-id`; the profile dir. About 450 KB after 15 runs.
- It writes nothing into the workspace except what tools create.

## Continue
- `--session-id <id>` (the id comes from the `session` event, e.g. `session-c85c70c1-…`). It is **cwd-scoped**: a session recorded in another directory is refused (exit 1). The workspace path must stay the same between runs; `/workspace` does. An unknown id gives exit 1.
- Proof: run 1 "Remember the word ORCHID. Reply OK." → "OK. I'll remember ORCHID."; run 2 `--session-id` → turn 2, "ORCHID.", exit 0.

## Mid-turn steering
- `--profile sdk` (JSON-RPC stdio: `initialize`, `session/prompt`, `shutdown`; notifications `session.event`/`session.status`): `session/prompt` calls `agent.followup()`, which queues for the **next turn**. That is not a steer and there is no cancel method. Read in the source; not run.
- `--profile acp` (ACP v1: `session/new|resume|list|close|prompt|cancel`) allows one prompt at a time per session, so it can't steer either; `session/cancel` is its graceful stop (not tested).
- The way that works: the agent loop has `steer()` (next-step inbox), which the hook bridge uses. Setup: mount `dsh-hooks-claude-code` by `--patch`; a hook script drains a queue dir.
  - PostToolUse prints `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"<msgs>"}}`, which is appended to that tool result.
  - Stop prints `{"decision":"block","reason":"<msgs>"}`, which becomes `agent.steer()` and the turn continues.
  - Either prints nothing when the queue is empty.
  Messages land at the next tool boundary or turn end, never inside one model call. They don't appear in the `--json` stream; they are in the session log, so resume sees them.
- Test: counting task, message queued once count.txt had 3 lines → the model wrote 4 (that call was already in flight), then wrote `done.txt`=DONE, finished `completed`, exit 0, 8 tool calls in all. Stop path: a message queued before "Reply with just the word hello." → it answered hello, the Stop hook blocked, then it created `extra.txt`=EXTRA.

## Graceful stop
- dsh has no abort message in headless. SIGINT to the process group gives exit 130 within 0.06–0.12 s, `final` "", and the log is flushed up to the last committed event.
- Interrupted between steps (after "3"): resume answered "completed 1, 2, and 3; 4–30 not written".
- Interrupted while a bash call was running: the log ends with an unanswered `tool/call`. Resume still works ("appended 2 … started `printf '3'` … interrupted before a result was recorded").

## Worst case
Not needed: resume works. Fallback if the cwd-scoping ever breaks: decode the session log (zstd frames; Node `zlib.zstdDecompressSync` per frame) and hand the user/assistant/tool messages back as context.

## The folder we should ship
- harness.json: provider `deepseek` (`https://api.deepseek.com/anthropic`), `run.interrupt: "steered"`, `run.stdout: application/x-ndjson`, env `HOME={workspace}/.home`, `DSH_TELEMETRY_DISABLED=1`, `DSH_PERMISSION_MODE=danger-full-access`, files `AGENTS.md: {instructions}`. Fix the description to say "Anthropic Messages shape".
- run.sh: install artifacts. Then `export DEEPSEEK_BASE_URL="${HI_PROVIDER_URL%/}" DEEPSEEK_API_KEY="$HI_PROVIDER_KEY"`. Write `/tmp/dsh-patch.yml` with the `agent-default-model` row (model `${HI_MODEL:-deepseek-chat}`) and the `hooks-claude-code` row (configPath `/tmp/dsh-hooks.json`, whose commands run `python3 -I $HI_HARNESS_DIR/steer_hook.py /tmp/dsh-steer {post|stop}`). Then `exec python3 $HI_HARNESS_DIR/adapter.py`.
- adapter.py: reads stdin line 1 (the request; the task comes from `HI_TASK`), then starts `dsh --profile headless --patch /tmp/dsh-patch.yml --json ${HI_RESUME:+--session-id "$HI_RESUME"} "$HI_TASK" </dev/null` in its own process group, cwd = workspace. It pipes stdout through report logic. For each later stdin line (a JSON string), it writes `/tmp/dsh-steer/<ns>.msg` atomically (tmp + rename). On SIGINT or stdin EOF, it sends `killpg(SIGINT)` to dsh, waits, and exits with dsh's code. It ignores SIGINT itself so it can always write HI_OUTPUT.
- report.py (or the same logic in adapter.py): pass lines through flushed. On `session`, write HI_OUTPUT **immediately** with `resume`=sessionId. Sum usage from `status/step_end`. Status: `turn_end.reason.kind` completed → ok, aborted or no turn_end with exit 130 → interrupted, error or `error` event → fail. Answer = `final.text`. `cost_usd` = null (none reported). If report.py stays a separate pipe stage, run it with SIGINT ignored (`(trap '' INT; exec python3 report.py)`), or a SIGINT to the group kills it before it writes.
- artifacts: skills → `.dsh/skills/<name>/SKILL.md`; global instructions → `.dsh/AGENTS.md`; MCP and other config rows → `.dsh/cordis.patch.yml` (home layer; keep the run-time `--patch` for model and hooks so the two don't collide); user hooks → a hooks.json named by a hooks row in that patch.
- changes from today's folder: (1) `DEEPSEEK_DEFAULT_MODEL` is ignored, so HI_MODEL never takes effect today; use the `agent-default-model` patch. (2) No `DSH_PERMISSION_MODE`, so the default `workspace-write`+`ask` leaves dsh's own sandbox in play and fails closed on approvals. (3) report.py writes `session_id` only at the end; it should write `resume` early from the first line, and it reads `HI_SESSION_ID`, not `HI_RESUME`. (4) A SIGINT run (no turn_end) leaves status unset, and with `set -o pipefail` plus SIGINT the report stage can die before writing. (5) The harness.json description says OpenAI chat; it is Anthropic Messages. (6) There is no `run.interrupt`, adapter.py or steer hook yet.

## Evidence
- `dsh --version` → 0.2.0-rc.2 (/opt/node22, same as pin). `--profile headless --help` with `</dev/null` → help in 2 s; with stdin open it timed out at 30 s on the first try.
- "Reply with just the word PONG." (default model) → session/status/thinking/text/status/status/final, exit 0, 8.1 s (first run, includes profile init). Session log `request/header` shows `deepseek-flash`, `reasoningEffort high`.
- Patch model `deepseek-chat` + AGENTS.md → bash `uname -s`, answer ended "ZEBRA-42", exit 0, 4.5 s. Log `request/context` shows model `deepseek-chat`.
- Base URL check, ran with `DSH_PERMISSION_MODE=danger-full-access`: `/anthropic` ok, `/anthropic/v1` ok, root → 404, `/v1` → 404 (`turn_end.reason.kind=error`, code HTTP_404, exit 1).
- ORCHID: run 1 "OK. I'll remember ORCHID."; run 2 `--session-id` → "ORCHID.". Unknown id → exit 1; a different cwd → exit 1 "was recorded in …".
- SIGINT after 3 lines: exit 130 in 0.12 s, count=3, events {session 1, status 7, thinking 3, tool_call 3, tool_result 3, final 1}. Resume (3.7 s) named counting and "1, 2, and 3".
- SIGINT at the 3rd tool_call: exit 130 in 0.06 s, count=2. Resume named 2 and the interrupted `printf '3'`.
- Steer (hooks): STEER queued at 14.7 s with count=3. `printf 4` was already running. Then done.txt checked, `printf 'DONE' > done.txt`, read; final "Stopped counting and wrote `DONE` to `done.txt`.", exit 0 at 25.4 s; count.txt=4 lines.
- Proxy log (all runs with telemetry disabled): only `CONNECT api.deepseek.com:443`.
- Scripts: SCRATCH/harness-survey/work/deepseek-harness/bin/{sigint.py,steer_test.py,logproxy.py}, steer/{steer_hook.py,hooks.json,patch.yml}.
