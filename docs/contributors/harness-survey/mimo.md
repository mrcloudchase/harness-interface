# MiMo Code — mimo 0.1.15 (pin: @mimo-ai/cli@0.1.15)

**Verdict:** works with caveats — headless `mimo run --format json` and `mimo serve` both work through a CONNECT proxy to the provider only, but exit code is 0 even on API failure, it phones home by default (tracking.miui.com), and startup intermittently stalled ~2 min (3 of ~20 runs).
**Tier:** steered — via `mimo serve`: a second `POST /session/{id}/prompt_async` mid-work stopped counting at 4 and wrote done.txt; `POST /session/{id}/abort` idles in 0.25 s with the session saved. (Plain `run` + SIGINT dies instantly but the session is still resumable, so `continued` is the fallback.)

## Inputs
- Task: positional `mimo run [message..]` (also `-f/--file` attachments, `--command`). No stdin prompt.
- Headless: `run --format json`. Model: `-m provider/model` (e.g. `anthropic/claude-sonnet-4-6`, in bundled catalog). Cwd = workspace (`--dir` exists).
- Permissions: default config already allows bash/edit in `run` (counting ran with no flag, no prompt). `--dangerously-skip-permissions`/`--yolo` (env `MIMOCODE_DANGEROUSLY_SKIP_PERMISSIONS`) auto-approves the rest; I could not test it (my own sandbox refused the flag). Permissions also settable as `"permission"` in config. `--agent` (build|plan|compose), `--variant`, `--title`, `--thinking`.
- Instructions: reads both `AGENTS.md` and `CLAUDE.md` from the cwd and follows both (tested: AGENTS.md "end with PINEAPPLE" and CLAUDE.md "start with MANGO" both obeyed, also together). `MIMOCODE_DISABLE_INSTRUCTIONS`, `MIMOCODE_DISABLE_CLAUDE_CODE_PROMPT` exist (not tested).

## Provider
- Built-in `anthropic` provider (bundled `@ai-sdk/anthropic`), Messages API. Key: `ANTHROPIC_API_KEY`. Base URL: `MIMOCODE_CONFIG_CONTENT='{"provider":{"anthropic":{"options":{"baseURL":"https://host/v1"}}}}'` — it appends `/messages`, so the URL **must carry `/v1`** (error metadata showed `url: https://api.anthropic.com/v1/messages`). OpenAI-shaped providers exist in its catalog (OpenCode-style `@ai-sdk/openai-compatible` custom providers) — not tested.
- No login needed. Also registers `xiaomi`/`mimo` providers (MiMo Auto anonymous channel, api.xiaomimimo.com) — unused when `-m anthropic/...`.
- Honors `HTTPS_PROXY` (all traffic seen at my logging CONNECT proxy; NO_PROXY respected — keep it `127.0.0.1,localhost` because run talks to its own local server).
- Startup egress by default (seen at proxy): `models.dev:443` (catalog refresh; `MIMOCODE_DISABLE_MODELS_FETCH=1` stops it), `tracking.miui.com:443` (telemetry, on by default; `MIMOCODE_ENABLE_ANALYSIS=0` stops it), and a background `npm install @mimo-ai/plugin` into `~/.config/mimocode` (fails fast: "proxy.url must be a non-empty string", only a WARN). With the two env vars set, the only host contacted was api.anthropic.com. Auto-update: `MIMOCODE_DISABLE_AUTOUPDATE=1`.
- Key persistence: none. Grepped every home/workspace file for the key after runs: not found. A title-generation call (`agent=title`, same model) is made in addition to the main call (2 requests for a one-line reply).

## Artifacts it loads
- Config: `~/.config/mimocode/{config.json,mimocode.json,mimocode.jsonc}` (creates `mimocode.jsonc` stub), plus `MIMOCODE_CONFIG_CONTENT` (inline, merged), `MIMOCODE_CONFIG`, `MIMOCODE_CONFIG_DIR`; project config in workspace unless `MIMOCODE_DISABLE_PROJECT_CONFIG`. MCP: `"mcp"` key in config (OpenCode schema; not tested).
- Skills (tested with `mimo debug skill`): `~/.config/mimocode/skills/<n>/SKILL.md`, `~/.mimocode/skills/`, `~/.agents/skills/`, workspace `.mimocode/skills/`, `.agents/skills/`. `~/.claude/skills` and `.claude/skills` only with `MIMOCODE_ENABLE_CLAUDE_CODE_SKILLS=1`; `.opencode/skills` only with `MIMOCODE_ENABLE_OPENCODE_SKILLS=1`. ~38 builtin skills unpacked to `~/.local/share/mimocode/builtin_skills/` (`MIMOCODE_DISABLE_BUILTIN_SKILLS`).
- Commands `{command,commands}/**/*.md`, agents `{agent,agents}/**/*.md` under `.mimocode/` (and `.claude/commands`); plugins `.mimocode/plugin/*.ts` (its hook mechanism). No Claude-style settings.json hooks found. Imports `~/.claude` auth/sessions if present (`MIMOCODE_DISABLE_CLAUDE_IMPORT`, `MIMOCODE_DISABLE_CLAUDE_CODE`) — irrelevant with HOME=workspace/.home.

## Outputs
- `run --format json`: NDJSON on stdout; each line `{"type","timestamp","sessionID","part"}`. Types seen: `step_start`, `text` (part.text), `tool_use` (part.tool, part.state.{status,input,output}), `step_finish` (part.reason `tool-calls|stop`, part.tokens `{total,input,output,reasoning,cache:{read,write}}`, part.cost USD), `error` (error.name/data.message/statusCode). (`reasoning` with `--thinking`, not seen.)
- Resume id: `sessionID` on every event; first event is `step_start`, i.e. after startup + first model token (~3–5 s). On a provider error the `error` event still carries it.
- Exit code: 0 on success **and 0 on a 401 API error** — status must come from the `error` event. SIGINT: killed by signal (130), no final event.
- `serve`: SSE `GET /event` (`message.updated` info has cost/tokens per assistant message; `message.part.updated`/`message.part.delta`; `session.status` busy/idle; `session.idle`; `session.diff`; `metrics.*`; `server.heartbeat`). Session id known at `POST /session`, before any model call.

## State it keeps
- `~/.local/share/mimocode/mimocode.db` (SQLite: sessions/messages; first run prints a one-time migration notice on stderr), `.../log/*.log`, `.../storage/`, `.../builtin_skills/`, `.../compose/`, `.../memory/sessions/<id>/`; `~/.cache/mimocode/{version,bin}`; `~/.local/state/mimocode/{locks,llm-server}`; ~7 MB per fresh HOME.
- Writes into the workspace every run: `.mimocode/.gitignore` and `.mimocode/.cron-lock` (still written with `MIMOCODE_DISABLE_CRON=1`). This shows up as user changes.

## Continue
- `mimo run -s <sessionID> "<msg>"` (also `-c` last session, `--fork`). Proved: run 1 "Remember the word ORCHID. Reply OK." → `OK`; run 2 `-s ses_…` "Which word did I ask you to remember?" → "The word you asked me to remember is **ORCHID**." Same DB serves `serve` sessions.

## Mid-turn steering
- `mimo serve --port P` (127.0.0.1, no auth on loopback; optional `MIMOCODE_SERVER_PASSWORD` basic auth). Protocol: `POST /session` `{}` → `{id}`; `GET /event` SSE; `POST /session/{id}/prompt_async` `{"parts":[{"type":"text","text":"…"}],"model":{"providerID":"anthropic","modelID":"claude-sonnet-4-6"}}` → 204. A second prompt_async while busy is picked up at the next step. Rate limit: 20 prompt_async/min.
- Test: steer after 3 lines → counting stopped at **4**, `done.txt` = `DONE`, `session.idle` at 29 s, answer "Done. Counting stopped at 4…". PASS.
- `run --port P` + prompt_async to run's own server: not established (that attempt hit the startup stall). ACP (`mimo acp`): not retested; earlier research says it drops mid-work text. Earlier research also says a disconnected client stops its work: not retested — the adapter must stay connected.

## Graceful stop
- Own abort: `POST /session/{id}/abort` → `200 true`, `session.idle` 0.25 s later, no more numbers (3 stayed 3), follow-up prompt in the same session answered "writing 1 to 30… got through **3 numbers**". PASS. `serve` exits 0 on SIGINT.
- Plain `run` + `killpg(SIGINT)`: npm node wrapper and real binary both die by signal in 0.00–0.12 s (rc -2/130), no final event; counting stopped (3 → 3). Session saved: resumed `-s` "what were you doing…" → "writing the numbers 1 to 30… got through **3 numbers**". PASS.
- Wrapper note: `/opt/node22/bin/mimo` is a node script that `spawnSync`s `.../@mimo-ai/cli/bin/.mimocode` (or `MIMOCODE_BIN_PATH`); exec the binary directly in run.sh/adapter so signals and exit codes are the binary's.

## Worst case
Not needed: sessions persist in `$HOME/.local/share/mimocode/mimocode.db` and resume by id. If HOME were not kept, `mimo export <id>` / `mimo import <file>` move a session as JSON.

## The folder we should ship
- harness.json: provider `anthropic`; env `HOME={workspace}/.home`, `MIMOCODE_DISABLE_AUTOUPDATE=1`, `MIMOCODE_DISABLE_MODELS_FETCH=1`, `MIMOCODE_ENABLE_ANALYSIS=0`, `NO_PROXY=127.0.0.1,localhost`; files `AGENTS.md: {instructions}`; stdout `application/x-ndjson`; `run.interrupt: steered`; timeout generous (stall seen).
- run.sh: export `ANTHROPIC_API_KEY=$HI_PROVIDER_KEY`, `MIMOCODE_CONFIG_CONTENT` with baseURL `${HI_PROVIDER_URL%/}` normalized to end in `/v1`; `exec python3 adapter.py`. adapter.py: start `.mimocode serve --port <free>` in `$HI_WORKSPACE` (new session group), poll `GET /config`, open `GET /event`, session = `$HI_RESUME` or `POST /session`; print an early line with the id; `prompt_async` line 1's task; each later stdin line (JSON string) → `prompt_async`; SIGINT or stdin EOF → `POST /abort`, wait `session.idle`; exit after `session.idle` with no pending steer; then SIGINT serve. Translate SSE parts to the run-format events (`step_start/text/tool_use/step_finish/error` with `sessionID`) so report.py stays one parser. Non-steered fallback: `.mimocode run --format json -m anthropic/$HI_MODEL ${HI_RESUME:+-s "$HI_RESUME"} "$HI_TASK"`.
- report.py: write `resume` as soon as the first `sessionID` is seen (rewrite `HI_OUTPUT` then, again at end); answer = text parts of last step; usage/cost = sum of `step_finish` tokens/cost; status `fail` on any `error` event or no `step_finish` (don't trust exit code 0); `interrupted` when aborted.
- artifacts: skills → `.config/mimocode/skills/<n>/SKILL.md`; config/MCP/permissions → `.config/mimocode/mimocode.json` (key `mcp`, `permission`); commands → `.config/mimocode/commands/*.md`; agents → `.config/mimocode/agents/*.md`; global instructions → `.config/mimocode/AGENTS.md` (path by OpenCode convention, not tested).
- changes from today's folder: run.sh uses `HI_SESSION_ID` — the contract var is `HI_RESUME`; report.py writes `session_id`, contract key is `resume`, and never writes early; exit status relies on events only after the run (fine) but `status` defaults missing when no step_finish — set `fail`; telemetry + models.dev not disabled; runs the node wrapper (`mimo`) instead of the binary; default model fallback `claude-sonnet-4-5`; no `run.interrupt`; `--dangerously-skip-permissions` is fine to keep (untested here); workspace gets `.mimocode/` — consider removing `.mimocode/.cron-lock`/`.gitignore` after the run if they were not there before.

## Evidence
- Version: `mimo --version` → 0.1.15 (= pin; installed /opt/node22, binary 135 MB, no install).
- 401 run (key unset): one `error` event `x-api-key header is required`, exit 0.
- ORCHID: run1 `OK` (27.6k cache-write tokens, $0.1036); run2 `-s` → ORCHID. exit 0 both.
- Proxy (allowlist CONNECT proxy, only api.anthropic.com): default fresh HOME → DENY models.dev ×1, tracking.miui.com ×2, ALLOW anthropic ×2; with `MIMOCODE_DISABLE_MODELS_FETCH=1 MIMOCODE_ENABLE_ANALYSIS=0` → only anthropic ×2.
- SIGINT (run, wrapper and binary): 3 lines at 20–28 s, exit -2 in ≤0.12 s, 3 lines 4 s later, no lingering process; resume answered "3 numbers".
- serve steer: prompt_async 204 @4.3 s, 3 lines @20 s, steer 204, idle @29.1 s, count.txt 1–4, done.txt DONE, serve exit 0.
- serve abort: 3 lines @17.1 s, abort 200 true, idle in 0.25 s, still 3 lines, follow-up "got through 3 numbers".
- Stall: 3 runs (`--version` in a real HOME, one fresh-HOME `run`, one `run --port`) sat ~116–150 s before "creating instance" (log gap +116409ms), no output; 5 strace'd reruns and others took 5–7 s. Cause unknown (await before instance creation; disk contention possible).
