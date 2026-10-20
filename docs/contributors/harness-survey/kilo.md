# Kilo — kilo (@kilocode/cli) 7.8.12 (pin: 7.8.12)

**Verdict:** works — headless `kilo run --format json --auto` is clean, and only the provider host is contacted once four quiet switches are set.
**Tier:** steered — live: `kilo serve` + `POST /session/:id/prompt_async` sent after number 3 → count.txt stayed at 3, done.txt=DONE. `POST /session/:id/abort` stops the turn in ≤0.5 s and keeps the conversation.

## Inputs
- Task: positional `kilo run [message..]` (piped stdin is appended to it; `-f/--file` attaches files). Headless output: `--format json`.
- Permissions: `--auto` approves everything not explicitly denied. Without it, a headless run auto-rejects the request and fails ("pass --auto"), so it never stops to ask. Hidden aliases: `--yolo`, `--dangerously-skip-permissions`. For `serve` there is no `--auto`. Use env `KILO_PERMISSION='{"*":"allow"}'` (a JSON overlay merged into config.permission); tested.
- Model: `-m provider/model`. Others: `--agent`, `--variant` (reasoning effort), `--dir`, `--title`. The working dir is cwd (or `--dir`).
- Instructions: `AGENTS.md`, `CLAUDE.md` (unless `KILO_DISABLE_CLAUDE_CODE_PROMPT`) and `CONTEXT.md`, globbed up from cwd. Also `~/.config/kilo/AGENTS.md`, `~/.claude/CLAUDE.md` and config `instructions`. Followed: a workspace AGENTS.md saying "end with PINEAPPLE" gave the reply `4\n\nPINEAPPLE`.

## Provider
- Shapes: Anthropic Messages (`anthropic` provider, `ANTHROPIC_API_KEY`), OpenAI Responses (`openai` provider, `OPENAI_API_KEY`; wire URL seen as `<base>/responses`), and chat completions (custom provider `{"npm":"@ai-sdk/openai-compatible","options":{"baseURL":…,"apiKey":"{env:OPENAI_API_KEY}"}}`). All three tested live: anthropic, openai/gpt-5-mini and a cc/gpt-5-mini custom provider.
- Base URL: config `provider.<id>.options.baseURL`, passed inline as `KILO_CONFIG_CONTENT` (JSON). It must include `/v1`, because the provider appends `/messages` or `/responses` (error metadata showed `https://bogus.invalid/v1/messages`). DeepSeek: `https://api.deepseek.com/anthropic/v1` works.
- A model missing from the bundled catalog (e.g. `anthropic/deepseek-chat`) fails with "Model not found" and exit 1. Declare it with `provider.anthropic.models: {"deepseek-chat":{}}`. Its cost is then 0 unless `cost` is given.
- No login step. The key is never written to disk: all three keys' tails were scanned for across HOME and the workspace, 0 hits.
- `HTTPS_PROXY` is honored (Bun). Through my allowlist CONNECT proxy, a default run also tries `models.dev`, `us.i.posthog.com` (telemetry), and `ai-gateway.kilo.ai` (the Kilo gateway model list). Denied, those calls still let the run succeed, but they add seconds. With `KILO_DISABLE_MODELS_FETCH=1 KILO_DISABLE_AUTOUPDATE=1 KILO_TELEMETRY_LEVEL=off` plus config `"enabled_providers":["<id>"],"autoupdate":false,"share":"disabled","experimental":{"openTelemetry":false}`, the only CONNECT was api.anthropic.com. Cost is still computed from the bundled catalog.
- Retries: retryable errors (5xx) are retried for about 85 s by default. `KILO_SESSION_RETRY_LIMIT=0` fails fast (tested).

## Artifacts it loads
`kilo debug paths`: config `~/.config/kilo`, data `~/.local/share/kilo`, cache `~/.cache/kilo`, state `~/.local/state/kilo`, tmp `/tmp/kilo`. The config dir can be overridden with `KILO_CONFIG_DIR`.
- Config (tested with `kilo debug config`): `~/.config/kilo/{kilo.json,kilo.jsonc,opencode.json,config.json}`, `~/.kilo/kilo.json`, `~/.kilocode/kilo.json`. From the workspace: `kilo.json`, `opencode.json`, `.kilo/kilo.json`, `.kilocode/kilo.json` (`.opencode/opencode.json` is not read). `KILO_DISABLE_PROJECT_CONFIG` turns off workspace config. MCP goes in config key `mcp`.
- Skills (tested with `kilo debug skill`): `~/.config/kilo/{skill,skills}/<n>/SKILL.md`, `~/.claude/skills/`, `~/.agents/skills/`, `~/.kilo/skills/`, `~/.kilocode/skills/`, and the workspace's `.kilo/skills/` and `.claude/skills/`.
- From source, not tested: `{command,commands}/**/*.md`, `{agent,agents}/**/*.md`, `{mode,modes}/*.md` and `{plugin,plugins}/*.{ts,js}` under any config dir. Rules go in `~/.kilo/rules/*.md` (also `.kilocode/rules`). Hooks are JS plugins; there is no Claude-style hooks file.

## Outputs
- `--format json`: NDJSON. Each line is `{"type","timestamp","sessionID","part"}`. Types: `step_start`, `text` (`part.text`, `part.messageID`), `tool_use` (`part.tool`, `part.state.{input,output,status}`), `step_finish` (`part.reason` = tool-calls|stop, `part.cost` USD, `part.tokens.{input,output,reasoning,cache.read,cache.write}`), and `error` (`error.name`/`error.data.message`; this includes responseHeaders but not the key).
- Answer: the `text` parts of the last messageID. Usage and cost: sum the `step_finish` events.
- Resume id: `sessionID` on every event. The first line (`step_start`) arrives only when the model starts streaming, about 5 s or more in; no earlier event carries it. In serve mode the id comes from `POST /session` before any model call.
- Exit: 0 on success. 1 on error (bad key 401, unknown model, provider 502). Killed by SIGINT: −2 (shell 130).
- Serve SSE `GET /event`: `session.status{busy|idle}`, `session.idle`, `session.turn.open/close{reason}`, `session.queue.changed{queued[]}`, `session.error`, `message.updated`, `message.part.updated/delta`, `session.drain.interrupted`, `server.heartbeat`, etc.

## State it keeps
- `~/.local/share/kilo/kilo.db` (sqlite, WAL), which holds sessions, messages and parts.
- `storage/session_diff/<sid>.json`, `log/*.log`, `telemetry-id`, `repos/`.
- `~/.local/state/kilo-sandbox-policy/…`, `~/.config/kilo/{.gitignore,.bash-permission-migrated}`, and `~/.cache/kilo/models.json` when fetching is on.
- It writes nothing into the workspace: only the task's own files appeared. A run is about 0.5 MB.
- Its own bwrap sandbox is off by default (`sandbox.enabled` false).

## Continue
`kilo run -s <sessionID> …` (also `-c` for the last session, and `--fork`). Proven: run 1 "Remember the word ORCHID. Reply OK." returned "OK" (ses_ea85fb…). Run 2 with `-s` returned "ORCHID" under the same sessionID. Sessions created via serve resume the same way with plain `run -s`: it answered "…I reached **3**".

## Mid-turn steering
`kilo serve --port N --hostname 127.0.0.1` prints `kilo server listening on http://127.0.0.1:N` on stdout. Port 0 is random; parse that line. It warns when `KILO_SERVER_PASSWORD` is unset; with it set, use basic auth (user `kilo`).
- Create a session: `POST /session {}` → `{"id":"ses_…"}`.
- Prompt or steer (same call): `POST /session/:id/prompt_async {"model":{"providerID":"anthropic","modelID":"claude-sonnet-4-6"},"parts":[{"type":"text","text":"…"}]}` → 204.
- Stop: `POST /session/:id/abort` → 200 `true`. Status: `GET /session/status` (busy sessions only; `{}` when all are idle). Transcript: `GET /session/:id/message`.
- **Difference from OpenCode:** a prompt sent while the session is busy is queued (`session.queue.changed`). At the next step boundary, Kilo closes the current turn with `session.turn.close{reason:"superseded"}`, briefly emits `session.status idle` and `session.idle`, then opens a new turn for the queued text. An adapter must not treat that idle as "done". Treat the run as finished only on idle with the queue empty, or on `turn.close` reason ≠ superseded.
- `kilo run --attach URL -s <sid> --format json --auto "task"` also works as the output pump. It prints the same NDJSON, stays alive across the superseded hand-off, and exits 0 after the steered turn. It also answers permission prompts. SIGINT to this client does **not** stop the server-side turn: the server stayed busy and count kept rising. The adapter must call `/abort` itself.

## Graceful stop
- Abort API (tested): sent after number 3. Idle within 0.5 s, and the count stayed at 3. The in-flight assistant message gets `MessageAbortedError`, and `session.error` plus `session.drain.interrupted` are emitted. A follow-up prompt answered "I was writing numbers 1 to 30… I got through number **3**". `SIGINT` to idle `kilo serve` → exit 0 in 0.42 s.
- Plain headless `kilo run`, SIGINT to the process group after 3 numbers:
  - Through the npm wrapper (node), which forwards the signal and re-raises it: exit −2 in 0.13 s.
  - The native binary `…/@kilocode/cli-linux-x64/bin/kilo` signalled directly also exits by signal (−2) in 0.06 s. There is no in-process graceful handler, but parts are already persisted.
  - Nothing ran afterwards (count stayed at 3). `run -s <sid>` answered "writing numbers 1 to 30 … I got as far as writing **3**". So plain mode qualifies as `continued`.

## Worst case
Not needed, since resume works. If kilo.db were lost, `kilo export <sid>` writes `{info,messages[]}` JSON. That file could be kept in `$HOME` and handed back as context, or loaded with `kilo import <file>`.

## The folder we should ship
- harness.json: provider anthropic; `run.interrupt: "steered"`; env `HOME={workspace}/.home`; files `AGENTS.md: {instructions}`; stdout `application/x-ndjson`.
- run.sh: export the provider key under the right name. Set `KILO_CONFIG_CONTENT` = `{"provider":{"anthropic":{"options":{"baseURL":"<url without /v1>/v1"}}},"enabled_providers":["anthropic"],"autoupdate":false,"share":"disabled","experimental":{"openTelemetry":false}}`, plus `KILO_DISABLE_MODELS_FETCH=1 KILO_DISABLE_AUTOUPDATE=1 KILO_TELEMETRY_LEVEL=off KILO_PERMISSION='{"*":"allow"}'`. For a model not in the catalog, add `"models":{"<id>":{}}`. Then `exec python3 adapter.py`.
- adapter.py:
  1. Start `kilo serve --port 0` in its own session and parse the port.
  2. `POST /session`, or reuse `HI_RESUME`, and write the resume handle early.
  3. Start `kilo run --attach URL -s <sid> --format json --auto -m <model> "<task>"` and pipe its stdout through report.py. This makes the output identical to plain mode.
  4. For each later stdin line, `POST /session/<sid>/prompt_async` with the decoded text and the same model.
  5. On SIGINT or stdin EOF, `POST /abort`, wait for `GET /session/status` to be `{}`, then SIGINT the attach client and the serve process (exit 0 in about 0.4 s).
  6. Alternative without the attach client: subscribe to `/event` directly and stop at idle with an empty queue.
- report.py: as today, but write `resume` (not `session_id`). Write HI_OUTPUT early, as soon as the sid is known, and rewrite it at the end. Ignore SIGINT (`signal.signal(SIGINT, SIG_IGN)`) so it survives a process-group SIGINT and still writes. `status` is fail on an `error` event or a non-zero exit.
- artifacts: skills → `.config/kilo/skills/<n>/SKILL.md`; config, MCP, permission and plugins list → `.config/kilo/kilo.json`; commands → `.config/kilo/command/<n>.md`; agents → `.config/kilo/agent/<n>.md`; plugins (hooks) → `.config/kilo/plugin/<n>.js`; global rules → `.config/kilo/AGENTS.md`.
- changes from today's folder:
  - run.sh reads `HI_SESSION_ID`; the contract var is `HI_RESUME`.
  - report.py writes `session_id`, not `resume`, and does not handle SIGINT.
  - The default model is claude-sonnet-4-5.
  - The quiet switches are missing: today it contacts models.dev, posthog and ai-gateway.kilo.ai.
  - There is no `run.interrupt` and no adapter for steering.

## Evidence
- `kilo --version` → 7.8.12. The wrapper is node `bin/kilo`; the native Bun binary is `node_modules/@kilocode/cli-linux-x64/bin/kilo`. Source was read from git tag v7.8.12 (sparse clone, since deleted).
- Bogus baseURL → `error` event, url `…/v1/messages`, 502, exit 1 after about 86 s of retries. Real run "Reply with just: hi" → step_start/text "hi"/step_finish, cost 0.0628, exit 0, 8.7 s with the quiet config.
- Allowlist proxy log, default config: models.dev, us.i.posthog.com ×4, ai-gateway.kilo.ai ×2 DENY, api.anthropic.com ALLOW, and the run still succeeded. Quiet config: only `CONNECT api.anthropic.com:443`.
- DeepSeek via the anthropic shape with a declared model: tool call and "hi", exit 0. OpenAI `openai/gpt-5-mini` and `cc/gpt-5-mini` (openai-compatible) each ran `echo hello > h.txt` and replied hi; exit 0.
- Steer (serve, sonnet-4-6): prompt_async at t=3.1 s, number 3 at 17.9 s, steer at 17.95 s, `queue.changed` at 17.96 s, `turn.close superseded` and `idle` at 20.48 s, a new turn writes done.txt, `turn.close completed` at 23.97 s. Count was 3, done.txt=DONE, final reply "Counting stopped at 3."
- Steer through `run --attach`: count 4 (one step was in flight), done.txt written, run exit 0. SIGINT to the attach client: client exit −2, server still `busy` 4 s later.
- Abort: 200 true at 19.87 s, idle by 20.37 s, count 3. The resumed question got "got through number 3".
- Plain SIGINT: wrapper −2/0.13 s, native −2/0.06 s, count stayed 3. The resume answer named the counting and 3.
- Bad key: `error` APIError 401 "invalid x-api-key", exit 1.
