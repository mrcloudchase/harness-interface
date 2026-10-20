# OpenCode — opencode 1.19.3 (pin: opencode-ai@1.19.3)

**Verdict:** works — headless JSON runs, resume, live steering and abort all passed against api.anthropic.com with claude-sonnet-4-6.
**Tier:** steered — `opencode serve` + `POST /session/{id}/prompt_async` sent mid-turn stopped counting at 4 and wrote done.txt; `POST /session/{id}/abort` stopped within 0.2 s, and the conversation was saved.

## Inputs
- Task: positional `opencode run [message..]`. Headless output: `--format json`. Model: `-m provider/model` (e.g. `anthropic/claude-sonnet-4-6`). Resume: `-s <id>`; `-c` continues the last session; `--fork` copies the session first. Working directory: `--dir`, or the process cwd. **Gotcha:** run uses `process.env.PWD ?? cwd`, so a stale inherited `PWD` sends it to the wrong directory (it happened here from Python). bash sets `PWD` itself; from Python, set `PWD=ws` or pass `--dir`.
- Approvals: `--auto` approves every `permission.asked` (anything not explicitly denied). Without it, run auto-*rejects*. Run-created sessions deny `question`, `plan_enter` and `plan_exit`, so it never stops to ask. In serve mode no client answers permission asks. Set `OPENCODE_PERMISSION='{"*":"allow","question":"deny"}'` (JSON, merged into the `permission` config). A bash write outside the workspace also went through with no permission config (pb test), so this setting is a safety net and was not shown to be required.
- Instructions: it walks up from the cwd for `AGENTS.md`, then `CLAUDE.md`, then `CONTEXT.md`, and the first match wins. It also reads `~/.config/opencode/AGENTS.md` and `~/.claude/CLAUDE.md` (switch the latter off with `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1`), plus the `instructions` array in config. The model followed it: AGENTS.md said "end every reply with PINEAPPLE", and the reply was `4\n\nPINEAPPLE`.

## Provider
- It speaks Anthropic Messages (`anthropic` provider, through @ai-sdk/anthropic), OpenAI Responses (`openai/gpt-5-mini` with `OPENAI_API_KEY` worked) and any OpenAI-compatible chat API (custom provider with `"npm":"@ai-sdk/openai-compatible"`; that one was not tested).
- Key: `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`). There is no login step.
- Base URL: either `ANTHROPIC_BASE_URL` (proven: a bogus value gave a 404) or `OPENCODE_CONFIG_CONTENT='{"provider":{"anthropic":{"options":{"baseURL":"…/v1"}}}}'` (proven). The SDK appends `/messages`, so pass a URL ending in `/v1`. Oddly, a bare `https://api.anthropic.com` also worked, while curl to `/messages` gives a 404; I can't explain that, so always pass `/v1`.
- DeepSeek through the anthropic provider worked (`baseURL https://api.deepseek.com/anthropic/v1`, `-m anthropic/deepseek-chat`), but only once the model was declared: `"models":{"deepseek-chat":{}}`. Without that it failed with `UnknownError` (exit 1).
- Title generation runs on a "small model" chosen from the catalog (`claude-haiku-5-5` here), and that is an extra API call. On non-Anthropic providers it errors and is logged only. Set `small_model` to the same model, or ignore it.
- Startup fetches (seen through a logging CONNECT proxy):
  - `models.opencode.ai` catalog: off with `OPENCODE_DISABLE_MODELS_FETCH=1`, which falls back to the built-in snapshot.
  - `registry.npmjs.org`: a background `npm install @opencode-ai/plugin@1.19.3` into every config dir (`~/.config/opencode`, any `.opencode/`). It has no off switch. When denied it logs WARN "background dependency install failed" and the run carries on (5.5 s, exit 0). It leaves `package.json`/`.gitignore` there and about 28–86 MB in `~/.npm` when it succeeds.
  - `OPENCODE_DISABLE_AUTOUPDATE=1` just in case; no update fetch was seen from run or serve.
- `HTTPS_PROXY` is honored, and `NO_PROXY` too. Every call went through the proxy once `NO_PROXY` was narrowed to localhost.
- Key persistence: none. A scan of HOME, the workspace and the SQLite WAL found no key. `opencode auth login` would write `~/.local/share/opencode/auth.json` (not used).

## Artifacts it loads
- Config: `~/.config/opencode/opencode.json[c]` (created empty on first run), `OPENCODE_CONFIG` (a file), `OPENCODE_CONFIG_CONTENT` (inline JSON, merged last), `OPENCODE_CONFIG_DIR`, `~/.opencode/`. From the workspace it also loads `opencode.json[c]` and `.opencode/` up the tree; switch those off with `OPENCODE_DISABLE_PROJECT_CONFIG=1`. XDG_* variables move all of these.
- Each config dir (`~/.config/opencode/`, `.opencode/`) holds:
  - `{command,commands}/**/*.md` (custom commands)
  - `{agent,agents}/**/*.md` and `{mode,modes}/*.md`
  - `{plugin,plugins}/*.{ts,js}` (plugins are its hooks)
  - `{skill,skills}/**/SKILL.md`
- Skills are also read from `~/.claude/skills/**/SKILL.md`, `~/.agents/skills/**`, the same paths up the workspace tree, and config `skills.paths`. Switches: `OPENCODE_DISABLE_EXTERNAL_SKILLS` and `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`.
- MCP: the `mcp` key in opencode.json. Permissions: the `permission` key, or `OPENCODE_PERMISSION`.

## Outputs
- `run --format json` writes NDJSON, one event per line. Each event is `{"type","timestamp","sessionID","part"|"error"}`. Types:
  - `step_start`
  - `text` (`part.text`; emitted when the text part ends)
  - `tool_use` (`part.tool`, `part.state.{status,input,output}`)
  - `step_finish` (`part.reason` stop|tool-calls|error, `part.tokens{input,output,reasoning,cache{read,write}}`, `part.cost` in USD)
  - `reasoning` (only with `--thinking`)
  - `error` (`error.name`/`error.data.message`, e.g. APIError 404)
- Answer: the text parts of the last assistant message. Usage and cost: sum the `step_finish` events.
- Resume id: `sessionID` is on every event, but the first event arrives only at the first model step (about 5–8 s in). The session itself is created and saved about 3–5 s earlier, so a SIGINT before then leaves no handle on stdout.
- Exit codes: 0 on success. 1 on a provider or config error (an `error` event is printed). SIGINT kills it by signal (−2, i.e. 130). An aborted session (`/abort`) still exits 0, with `MessageAbortedError` on the message.
- `run --attach` race: it exits as soon as `session.prompt` returns and can drop the last `text`/`step_finish` events. That happened in s1, where the final "Done…" text never printed. An adapter reading `/event` itself does not have this problem.

## State it keeps
- `~/.local/share/opencode/opencode.db` (+ `-wal`/`-shm`): SQLite holding sessions, messages and parts, written as the turn goes.
- `~/.local/share/opencode/log/opencode.log`, `…/snapshot/` (a git object store of the workspace for undo, created in git workspaces), `…/repos/`.
- `~/.local/state/opencode/locks/`, `~/.cache/opencode/` (`models.json` if fetched, `bin/`), `~/.config/opencode/{opencode.jsonc,.gitignore}`.
- In the workspace: nothing in a plain directory. A git workspace gets a project-id file at `.git/opencode`, which does not show in `git status`. A `.opencode/` dir in the workspace gets a `.gitignore` (and `package.json`/`node_modules` if npm is reachable).

## Continue
`opencode run --format json --auto -m anthropic/claude-sonnet-4-6 -s <sessionID> "<text>"`, with the same `$HOME`. "Remember the word ORCHID. Reply OK." → `OK`; the resumed run → `ORCHID`, same id. `-c` worked too, in a git workspace (TULIP). Over HTTP: reuse the id in `prompt_async`.

## Mid-turn steering
- Protocol:
  1. `opencode serve --port 0 --hostname 127.0.0.1` (cwd = workspace). Wait for the stdout line `opencode server listening on http://127.0.0.1:N`. A request sent before that line hung forever, twice.
  2. `POST /session?directory=WS` with `{}` returns `{"id":"ses_…"}`.
  3. Open `GET /event?directory=WS` (SSE, `data: {"type","properties"}`) before prompting.
  4. `POST /session/{id}/prompt_async?directory=WS` with `{"model":{"providerID":"anthropic","modelID":"claude-sonnet-4-6"},"parts":[{"type":"text","text":"…"}]}` returns 204. The first one starts the turn. One sent while busy is queued, and the running loop picks it up at its next step.
- Turn ends at the SSE event `session.status` with `status.type=="idle"` for the session.
- Events to translate: `message.part.updated` (`properties.part` has the same shape as run's `part`) and `session.error`.
- Steering a prompt_async that has no `model` field: not tested.
- Result, twice:
  - `run --attach -s SID` + curl-style prompt_async: count stopped at 4, `done.txt`=DONE, final text "Counting stopped (count.txt has 1–4)".
  - Prototype adapter (stdin JSON-string line → prompt_async): count stopped at 4, `done.txt`=DONE, exit 0 9.5 s after the steer.

## Graceful stop
- Its own: `POST /session/{id}/abort?directory=WS` returns `true`. Tested twice: counting stopped at 3, and the client or adapter exited in 0.2–0.4 s with exit 0. The last assistant message carries `error.name=MessageAbortedError`. Resumed (by plain `run -s`, and by the adapter with `HI_RESUME`): "I got through number **3**".
- Plain `opencode run`: SIGINT to the process group killed it in 0.1 s, exit −2 (130), with no final event and no stray processes. Nothing more was counted. The session was saved, and `run -s` answered "writing numbers 1 to 30… got as far as 1, 2, 3 (3 interrupted mid-execution)". Pass.

## Worst case
Not needed, since resume works. Fallback if it ever is: `opencode export <sessionID>` gives the session as JSON, and `opencode import <file>` loads it into a new `$HOME`.

## The folder we should ship
- harness.json: provider `anthropic`. `files: {"AGENTS.md": "{instructions}"}`. `run.env`: `HOME={workspace}/.home`, `OPENCODE_DISABLE_MODELS_FETCH=1`, `OPENCODE_DISABLE_AUTOUPDATE=1`, `OPENCODE_PERMISSION={"*":"allow","question":"deny"}`. `run.stdout` `application/x-ndjson`. `run.interrupt: "steered"`.
- run.sh: artifacts loop as today; `cd "$HI_WORKSPACE"` (so `PWD` is correct); `export ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"`. Put the base URL (`${base%/v1}/v1`), the model's `models` entry (so non-catalog ids work) and `small_model` = the same model into `OPENCODE_CONFIG_CONTENT`. Then `python3 "$HI_HARNESS_DIR/adapter.py" | python3 "$HI_HARNESS_DIR/report.py"`.
- adapter.py (prototype, tested: `work/opencode/proto/adapter.py`):
  - Start `serve --port 0` with `start_new_session`, parse the URL, create or reuse the session (`HI_RESUME`), and print `{"type":"session","sessionID":…}` at once (about 2 s).
  - Subscribe to `/event` and `prompt_async` the task (`HI_TASK`). Each later stdin line, a JSON string, becomes a `prompt_async`.
  - SIGINT, SIGTERM or stdin EOF → `POST /abort`.
  - Re-emit the run-shaped events (`step_start`/`text`/`tool_use`/`step_finish`/`reasoning`/`error`), deduped by part id. Exit at idle and `killpg` the server.
  - Talk to localhost with no proxy (`ProxyHandler({})`).
  - Answering `permission.asked` (`POST /permission/{id}/reply` with `{"reply":"once"}`, the way run `--auto` does) would be a second safety net; not tested.
- report.py:
  - Pass lines through, and ignore SIGINT (`signal.SIG_IGN`) so the group SIGINT doesn't kill it before it writes.
  - On the first `sessionID`, write `{"resume": id, "status": "running"}` to `HI_OUTPUT` early.
  - Answer: the text of the last message. Usage and `cost_usd`: sums over `step_finish`. Status: `fail` on an `error` event or `reason=="error"`, `ok` at the end; an abort shows as `MessageAbortedError`, treat it as stopped.
- artifacts:
  - `opencode.json` → `.config/opencode/opencode.json` (mcp, permission, agents, plugins config)
  - `AGENTS.md` → `.config/opencode/AGENTS.md`
  - skills → `.config/opencode/skills/<name>/SKILL.md`
  - commands → `.config/opencode/commands/<name>.md`
  - agents → `.config/opencode/agents/<name>.md`
  - plugins/hooks → `.config/opencode/plugins/<name>.ts`
- changes from today's folder:
  - (1) run.sh resumes from `HI_SESSION_ID`, but the contract var is `HI_RESUME`, so continue never resumes.
  - (2) report.py writes `session_id`, not `resume`, and writes only at the end. It dies on the group SIGINT and then writes nothing.
  - (3) There is no adapter and no `run.interrupt`.
  - (4) The default model is `claude-sonnet-4-5`; pass `HI_MODEL` through.
  - (5) No `OPENCODE_DISABLE_MODELS_FETCH`, so every run tries models.opencode.ai, and that host is blocked in the sandbox.
  - (6) No `models` entry, so non-catalog models (e.g. `deepseek-chat`) fail on the deepseek provider.
  - (7) There is no `cd`/`--dir` guard for `PWD`.

## Evidence
- Setup: fresh HOME per run under `work/opencode/home-*`, scratch `ws-*` as cwd, `CLAUDE*`/`ANTHROPIC*`/`OPENAI*`/`CCR*` etc. stripped. Traffic went through a logging CONNECT proxy chained to `$HTTPS_PROXY`, set to allow only api.anthropic.com unless noted.
- a1 (defaults): CONNECT models.opencode.ai, registry.npmjs.org, api.anthropic.com. The stale PWD ran it in the parent dir, so AGENTS.md was ignored.
- a3 (flags, PWD fixed): only api.anthropic.com, with npm DENIED (non-fatal). Output `step_start,text("4\n\nPINEAPPLE"),step_finish`, exit 0, 5.5 s, cost 0.0299 on the first run.
- p1 `baseURL …/v1` → HELLO.
- p2 `ANTHROPIC_BASE_URL=…/bogus/v1` → `error` APIError 404, exit 1.
- p3 config `baseURL …/bogus` → 404, exit 1.
- p4 DeepSeek: `UnknownError` until `models.deepseek-chat` was declared, then HELLO.
- p5 `openai/gpt-5-mini` → HELLO.
- c1 ORCHID → OK / ORCHID (same id). g1 TULIP with `-c` → TULIP; `.git/opencode` written.
- s1: serve + `run --attach -s SID --auto` + `prompt_async` at count 3 → 204. Count ended at 4, done.txt DONE, run exit 0 12.6 s later. The messages list shows the user steer between tool steps. The final text event was missing from run's stdout (race).
- ab1: `/abort` at count 3 → 200 `true`. run exit 0 in 0.2 s; count stayed 3; MessageAbortedError. Resume → "got through number 3".
- si1: plain run, killpg SIGINT at count 3. Exit −2 in 0.1 s; first sessionID line had appeared at 8.0 s. Resume → "1, 2, 3 (3 interrupted)".
- d1/d2/d3: prototype adapter. Steer → count 4 + DONE, exit 0; events step_start×9, tool_use×8, text×3, session×1. SIGINT → stopped at 3 in 0.2 s, exit 0. EOF → stopped at 3 in 0.4 s. d2 resumed with HI_RESUME → "got as far as 3".
- Serve hang: a request sent before the "listening" line went unanswered for more than 120 s (st1); probes sent after it got answers in 0.4 s (sp1–sp3).
- Clean-up: deleted the `~/.npm` caches (about 160 MB) and the models.json copies. Key scan of the work dir: none found; work dir is 31 MB. One stray `/home-si1` (368 KB opencode HOME, no key in it) was created by a script mistake. The safety check blocked removing it, so it needs a manual `rm -rf /home-si1`.
