# OpenHands — openhands 1.16.0 (pin: openhands==1.16.0; sdk/tools 1.21.0, litellm 1.105.1)

**Verdict:** works with caveats: headless runs, resumes and proxies cleanly, but `--headless` can't be steered, and on SIGINT it saves status `error` and re-runs the interrupted command on resume.
**Tier:** steered: an `adapter.py` on the bundled SDK (`conversation.send_message` while `run()` works) stopped counting at 3 and wrote done.txt. SIGINT/EOF → `pause()` exits 0 in 1.4 s and resumes cleanly. ACP `session/prompt`-while-busy also passed.

## Inputs
- Task: `-t TEXT` or `-f FILE`. Headless: `--headless` (requires -t/-f; forces NeverConfirm and `--exit-without-confirmation`, so `--always-approve` is redundant). `--json` = NDJSON events. stdin is never read (verified: lines written mid-run were ignored).
- Model/key/URL: only via `--override-with-envs` + `LLM_MODEL` (litellm form `anthropic/claude-sonnet-4-6`), `LLM_API_KEY`, `LLM_BASE_URL`. Without the flag, env is ignored and a missing `~/.openhands/agent_settings.json` fails with "Headless mode requires existing settings". No model or cwd flag. Work dir = cwd (`OPENHANDS_WORK_DIR` overrides).
- Instruction files: cwd (and git root) `AGENTS.md`/`agent.md`/`CLAUDE.md`/`GEMINI.md`/`.cursorrules` (case-insensitive) go into `<REPO_CONTEXT>` wrapped in `<UNTRUSTED_CONTENT>` with "coding style… only". Verified: AGENTS.md "end every reply with PINEAPPLE" was ignored. The same text placed ahead of the task was obeyed ("4.\n\nPINEAPPLE"). User-level skills are wrapped the same way, so there is no trusted instruction file.
- Also: `cwd/.env` is loaded with python-dotenv (override=False).

## Provider
- litellm. `anthropic/<m>` → Anthropic Messages (`LLM_BASE_URL=https://api.anthropic.com`, no `/v1`; verified behind an allowlist proxy). `openai/<m>` → OpenAI chat completions, except model names containing `gpt-5`/`codex-mini-latest`, which use the Responses API (verified `openai/gpt-5-mini` + `https://api.openai.com/v1`). DeepSeek works only in the OpenAI shape (`openai/deepseek-chat` + `https://api.deepseek.com/v1`). `anthropic/deepseek-chat` + `https://api.deepseek.com/anthropic` fails with 400 `tools[0]: unknown variant custom`.
- No login step. HTTPS_PROXY is honoured (httpx and git).
- Startup fetches other hosts (seen through a logging CONNECT proxy). All got 403 fast, and the run still worked:
  - raw.githubusercontent.com: litellm cost map and beta headers. Disable with `LITELLM_LOCAL_MODEL_COST_MAP=True` and `LITELLM_LOCAL_ANTHROPIC_BETA_HEADERS=True`.
  - github.com: `git clone --depth 1` of OpenHands/extensions (public skills) into `~/.openhands/cache/skills` (9.9 MB). Hard-coded, with no switch.
  - pypi.org: version check from the splash screen. No switch.
  - On an open network, one resumed run hung >190 s at "Initializing agent..." (probably that git fetch; unconfirmed).
- Key persistence: none for headless+env (scanned the whole dir: 0 hits; `base_state.json` stores `"api_key": "**********"`). `AgentStore.save` (the TUI settings screen) writes the key in clear to `~/.openhands/agent_settings.json`.

## Artifacts it loads
- Home (`OPENHANDS_PERSISTENCE_DIR`, default `~/.openhands`): `agent_settings.json` (LLM, condenser, tools), `cli_config.json`, `mcp.json` (`{"mcpServers":{...}}`), `hooks.json`, `profiles/`.
- Skills: `~/.agents/skills/`, `~/.openhands/skills/`, `~/.openhands/microagents/` (`<name>/SKILL.md` or `.md` with frontmatter triggers).
- Workspace: `.agents/skills/`, `.openhands/skills/`, `.openhands/microagents/`, `.openhands/hooks.json` (wins over the home one: the first file found is used), and the third-party files above.

## Outputs
- stdout mixes text and JSON. Non-JSON lines: "OpenHands CLI terminal UI may not work…" ×2, "Initializing agent...", "✓ Agent initialized with model: …", "Agent is working"/"Agent finished", a Rich CONVERSATION SUMMARY box, "Goodbye! 👋", `Conversation ID: <hex>`, `Hint: run openhands --resume <uuid>`. Set TERM=dumb or you get ANSI codes.
- JSON lines are `event.model_dump()`, one per line, with `kind` in: MessageEvent (source user/agent; answer = agent `llm_message.content[].text`), ActionEvent, ObservationEvent, AgentErrorEvent, ConversationErrorEvent (`code`, `detail`), PauseEvent, CondensationRequest, Condensation, UserRejectObservation. SystemPromptEvent is suppressed.
- **Stdout is block-buffered on a pipe** (everything arrived at exit) unless `PYTHONUNBUFFERED=1`; with it, events stream live.
- Usage and cost are not on stdout. They are in `~/.openhands/conversations/<hex>/base_state.json`: `stats.usage_to_metrics.{agent,condenser}.accumulated_cost` and `.accumulated_token_usage.{prompt,completion,cache_read,cache_write}_tokens`. They are **cumulative over resumed runs**, so report the delta.
- Exit code is 0 on success, on an auth error (ConversationErrorEvent AuthenticationError) and on SIGINT. Only argparse errors (2) and missing env (1) are non-zero.
- Resume id: `Conversation ID` is printed only at exit, but `--resume <fresh uuid4>` creates a new conversation under that id (verified), so the harness knows it before launch.

## State it keeps
- `~/.openhands/conversations/<hex>/{base_state.json,events/event-NNNNN-<uuid>.json}`, plus `~/.openhands/cache/{skills,jinja}`, `~/.openhands/profiles/` and `~/.bash_history`.
- tmux server `tmux -Lopenhands` (socket `/tmp/tmux-0/openhands`, own session, survives killpg) when tmux exists; otherwise a subprocess terminal.
- Nothing is written into the workspace (only the agent's own files).

## Continue
`--resume <uuid|hex>` (`--resume --last` = most recent). Run 1 `--resume <new uuid>` "Remember the word ORCHID. Reply OK." → "OK.". Run 2 `--resume` same → "The word you asked me to remember is **ORCHID**." Tools come from the saved base_state.

## Mid-turn steering
- `--headless`: none (stdin ignored; count went 3→6 after the steer line).
- **SDK (recommended):** `conv.send_message(text)` from a stdin thread while `conv.run()` runs in another. It blocks until the current step releases the state lock, then the run loop takes it on the next step. PASS: steer at count 3 → count stayed 3, done.txt written, status finished, exit 0 8.6 s later.
- **ACP** (`openhands acp --always-approve`, NDJSON JSON-RPC: `initialize{protocolVersion:1}`, `session/new{cwd,mcpServers:[]}` → `sessionId`, `session/prompt{sessionId,prompt:[{type:text,text}]}`, notification `session/cancel{sessionId}`):
  - A second `session/prompt` while the first runs worked: count 3, done.txt, both answered `{"stopReason":"end_turn"}` together 6.8 s later.
  - It is racy by construction: `prompt()` calls `send_message` synchronously on the event loop and starts a second `conversation.run` thread alongside the first.
  - ACP ignores `--override-with-envs` and needs `~/.openhands/agent_settings.json`. A keyless one plus `ANTHROPIC_API_KEY` in env worked.
  - Updates: `session/update` with `agent_thought_chunk`/`agent_message_chunk`/`tool_call`/`tool_call_update`; cumulative tokens/cost in `params._meta.field_meta["openhands.dev/metrics"]`.

## Graceful stop
- Headless SIGINT (killpg at count 3): exit rc 0 in 3.1 s, prints `Conversation ID`. Saved with `execution_status: error` and the interrupted ActionEvent has no observation. On resume the SDK **re-executed it** (count.txt became 1 2 3 3) and then answered correctly ("count.txt contains 1–3 … next step: write 4").
- SDK `conversation.pause()` (adapter on SIGINT): stops after the current step, rc 0 in 1.4 s, status `paused`, PauseEvent saved, no duplicate. A resumed run said "I got through **3 out of 30**". PASS.
- ACP `session/cancel`: paused 1.0 s later, prompt answered `stopReason:"end_turn"` (not `cancelled`). The next prompt in the same session said "3 out of 30". A fresh `openhands acp --resume <id>` (history replayed as updates) answered "count.txt, last number 3".
- ACP **ignores SIGINT and stdin EOF**: it kept counting to 12 and was still alive 30 s later, even when idle.

## Worst case
Not needed: resume works. Fallback: the `events/*.json` of `~/.openhands/conversations/<hex>/` (or `openhands view <id>`) handed back as context.

## The folder we should ship
- **harness.json:**
  - provider `anthropic`; `run.interrupt: "steered"`; stdout `application/x-ndjson`.
  - env: `HOME={workspace}/.home`, `OPENHANDS_SUPPRESS_BANNER=1`, `PYTHONUNBUFFERED=1`, `TERM=dumb`, `LITELLM_LOCAL_MODEL_COST_MAP=True`, `LITELLM_LOCAL_ANTHROPIC_BETA_HEADERS=True`.
- **run.sh:**
  - Exec `"$(dirname "$(readlink -f "$(command -v openhands)")")/python" "$HI_HARNESS_DIR/adapter.py"`, piping its stdout through `report.py`.
  - Export `LLM_MODEL` (add `anthropic/` if there is no prefix), `LLM_API_KEY=$HI_PROVIDER_KEY` and `LLM_BASE_URL=${HI_PROVIDER_URL%/}`.
  - Keep the artifacts loop.
- **adapter.py** (prototype tested: `work/openhands/scripts/sdk_adapter.py`):
  - Read line 1 (request). Prepend `instructions` to the task. Use `uuid = HI_RESUME or uuid4()` and print `{"kind":"session","id":…}` first.
  - Build the conversation with `openhands_cli.setup.setup_conversation(uuid, NeverConfirm(), visualizer=None, event_callback=print-json, console=Console(file=sys.stderr), env_overrides_enabled=True, critic_disabled=True)`. This is the same agent as the CLI headless run.
  - `send_message(task)`, then `run()` in a thread. Each later stdin line goes to `send_message(json.loads(line))`. SIGINT or EOF → `conv.pause()`. If a steer arrives after `run()` returns, re-run.
  - Finally print `{"kind":"result","status","cost","usage"}` from `conv.conversation_stats.get_combined_metrics()`.
- **report.py:**
  - `resume` comes from the first `session` line: write `$HI_OUTPUT` early with it.
  - `answer` = last agent MessageEvent text.
  - `status` = fail on ConversationErrorEvent/AgentErrorEvent or result status `error`. `paused` = stopped by the user, resumable.
  - `usage` and `cost_usd` come from the result line (combined agent+condenser; cumulative over a resumed conversation, so subtract the previous run's).
  - Keep the passthrough.
- **artifacts:** skills → `.agents/skills/<name>/SKILL.md`; MCP → `.openhands/mcp.json`; hooks → `.openhands/hooks.json`. Not agent_settings.json: it would carry a key, and env overrides replace it.
- **Changes from today's folder:**
  - Reads `HI_REQUEST`/`HI_SESSION_ID` and writes `session_id`; the contract now is the request on stdin, `HI_RESUME`, and `resume`/`usage`/`cost_usd`.
  - No `PYTHONUNBUFFERED`, so nothing streams.
  - The resume id is only known at exit; pass `--resume <uuid4>` up front.
  - Usage and cost are never reported.
  - No litellm offline env.
  - Default model `claude-sonnet-4-5`.
  - SIGINT on the plain CLI leaves status `error` and re-runs the cut-off command on resume. If staying on the CLI, it is `continued` at best; the adapter fixes this.

## Evidence
- `openhands --version` → "OpenHands CLI 1.16.0". The first cold start took >120 s (disk); later starts take 5–7 s.
- basic: `--headless --json --override-with-envs -t "What is 2+2?"` rc 0 15 s; all lines landed at t=13.83 (buffered). With `PYTHONUNBUFFERED=1`, lines streamed (10.8 s, 44.7 s, 46.5 s…).
- Allowlist-proxy run (`HTTPS_PROXY` = logging proxy allowing only api.anthropic.com, `NO_PROXY` empty): rc 0 12.8 s, hi.txt written. DENY log: raw.githubusercontent.com ×4, github.com ×5, pypi.org ×1. With the LITELLM_* vars, raw.githubusercontent.com dropped to 1 hit.
- Bad key: rc 0, ConversationErrorEvent code AuthenticationError, and the summary box showed the system prompt.
- Headless SIGINT at count 3: rc 0, 3.1 s. Resume "Do not run any commands. What were you doing…": the ObservationEvent shows `echo 3 >> count.txt` re-run; count.txt = 1 2 3 3.
- SDK steer: count 3 → steer `"Stop counting now. Instead write the word DONE into done.txt and finish."` → done.txt, count 3, exit 0 after 8.6 s, cost $0.10.
- SDK SIGINT: PauseEvent, status paused, rc 0 in 1.4 s. Resume answered "3 out of 30"; count.txt stayed 1 2 3.
- ACP: initialize 5 s, session/new 3–5 s. Steer prompt id 4 at t=27.8; ids 3 and 4 were both answered at t=34.6; count 3, done.txt.
- ACP cancel: answered in 1.0 s; ACP SIGINT and EOF: still alive 30 s later, count reached 12; killed with SIGKILL.
- Providers: `openai/gpt-5-mini` (Responses, rc 0, hi.txt), `openai/deepseek-chat` @ `https://api.deepseek.com/v1` (rc 0, hi.txt), `anthropic/deepseek-chat` @ `/anthropic` (400 tools type custom).
- Cleanup: deleted the skills caches, killed the leftover `tmux -Lopenhands` servers and the ACP process; key scan of work dir: 0 hits. Work dir 15 MB.
