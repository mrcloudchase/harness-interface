# Stage 2 report: opencode (OpenCode, sst) — opencode-ai@1.19.3

`R` = `scratchpad/rebuild`, `EV` = `scratchpad/ev/` (every run's result JSON + full stdout/stderr), 2026-10-20.
1.19.3 is still the latest stable version on npm (published 2026-10-16; only `0.0.0-dev-*` builds came after it).

**Verdict: works. Tier: `steered`**, both locally and in the hardened docker sandbox, with `--secret gateway`
and `--secret file`, on three provider paths (Anthropic and DeepSeek in the anthropic-messages shape,
OpenAI in openai-responses, DeepSeek in openai-chat). No key reached the sandbox, a log or the disk.
`hi_adapter.py` is byte-identical: `hirun.py check`, and the 7 unit tests pass.

**Providers:** the Anthropic key ran out of credit at about 06:36. Every `claude-sonnet-4-6` proof below
ran before that. Later proofs ran on OpenAI `gpt-5-mini` (openai-responses) or DeepSeek `deepseek-chat`
(Anthropic shape, `https://api.deepseek.com/anthropic`). After the outage, Anthropic runs returned
`fail` with "credit balance is too low": the folder reported the provider's error correctly, which also
shows the key reached Anthropic in file mode.

## The folder: `R/harnesses/opencode/`
| file | what it does |
|---|---|
| `harness.json` | provider default anthropic; apis: all 3; install egress `registry.npmjs.org, pypi.org, files.pythonhosted.org`; `files: {".home/.config/opencode/AGENTS.md": "{instructions}"}` (OpenCode reads its global AGENTS.md, so nothing is written into the user's tree); `run`: steered, ndjson, 900 s, stop 15 s |
| `install.sh` | `npm i -g opencode-ai@1.19.3`. Then it deletes the two 178 MB platform packages: the postinstall has already hard-linked the AVX2 binary to `bin/opencode.exe` (355 MB down to 178 MB). Then it installs **ripgrep 15.1.0** from its PyPI wheel, pinned by sha256 (see Findings 2) |
| `run.sh` | `cd` + `export PWD=$HI_WORKSPACE` (OpenCode trusts `$PWD`). Quiet switches: `OPENCODE_DISABLE_{MODELS_FETCH,AUTOUPDATE,LSP_DOWNLOAD,DEFAULT_PLUGINS,CLAUDE_CODE,EMBEDDED_WEB_UI}=1` and `npm_config_offline=true` (Findings 3). Then it `exec`s the adapter |
| `adapter.py` (230 lines) | Builds `OPENCODE_CONFIG_CONTENT` for each request (provider id from `HI_PROVIDER_API`, `baseURL` = URL + `/v1`, `apiKey: "{file:$HI_PROVIDER_KEY_FILE}"`, the model declared, `small_model` = the same model, `enabled_providers` = [that one]). Then it runs `opencode serve --port 0 --hostname 127.0.0.1` with basic auth (a random `OPENCODE_SERVER_PASSWORD`) and waits for "listening". `POST /session {"title":"hi"}`, or reuses the resume id after `GET /session/{id}`. The resume id goes into HI_OUTPUT before any model call. It subscribes to `GET /event` (SSE) and, on `server.connected`, sends `prompt_async`. A steer is another `prompt_async` (queued if it arrives before the task). Stop = `POST /abort`. `permission.asked` gets a "once" reply and `question.asked` is rejected, so the run can never hang on a prompt. Done = `session.status` idle, with every prompt sent turned into a user message and the last assistant message newer than the last user message |
| `home/.config/opencode/opencode.json` | the static config: `autoupdate:false`, `share:"disabled"`, `snapshot:false`, `lsp:false`, `formatter:false`, `permission {"*":"allow", question/plan_enter/plan_exit: deny}` |
| `hi_adapter.py` | the canonical copy, unchanged |

stdout is the NDJSON of `opencode run --format json`: `step_start`, `text`, `tool_use`, `step_finish`,
`reasoning` and `error`, each `{type,timestamp,sessionID,part}`, deduplicated by part id. On top of
those: `session` (first), `user` (OpenCode accepted a prompt; it is the steer ack) and `retry`.
Usage and cost are the sums over this response's `step_finish` parts, so they are per response.

## Evidence (all files in `EV/`)
| # | proof | where / provider / secret | result | numbers |
|---|---|---|---|---|
| L1 | one-shot + instructions (AGENTS.md "end with PINEAPPLE") | local / Anthropic sonnet-4-6 / gw | ok `4\n\nPINEAPPLE` | 5.8 s, $0.0303, 2 gateway calls (title + answer) |
| L2 | resume ORCHID | local / Anthropic / gw | `OK` → "…remember is **ORCHID**", same `ses_…` | 7.3 s / 5.7 s; run 2: 7951 cache-read tokens |
| L3 | steer after line 10 | local / Anthropic / gw (`local-steer.*`) | ok, steers 1/1, count `1 2 3`, done.txt DONE | 21.6 s; events session 1, user 2, step_start 8, tool_use 7, step_finish 8, text 1 |
| L4 | stop (SIGINT to group) → continue | local / Anthropic / gw (`local-stop.*`, `local-continue.json`) | stopped, then: "writing 1 to 30… got as far as **2**" | stop→exit **0.11 s**, exit 0, `MessageAbortedError` event |
| L5 | final-folder steer smoke test | local / DeepSeek / gw | ok, count 1–4, DONE | 15.4 s |
| D0 | install miss → hit | docker install container | miss **13.8 s**, hit **0.15 s**; 204 MB | door: allow npm ×3, pypi, files.pythonhosted |
| D1 | one-shot + instructions | docker / Anthropic / gw (`dk-gw-oneshot.*`) | ok `4\n\nPINEAPPLE` | 7.0 s; door: 2× `gateway POST /v1/messages -> 200`, nothing else |
| D2 | resume, steer, stop→continue | docker / Anthropic / **gw** (`dk-gw-*`) | ORCHID ✓; steer count `1 2 3` + DONE ✓; stopped at `1 2`, continue "got as far as **2**" ✓ | steer 24.1 s; stop→exit **0.33 s** via tini |
| D3 | same 4 proofs | docker / DeepSeek anthropic-shape / **file** (`dk-file-ds-*`) | ORCHID ✓; steer `1..4` + DONE ✓; stopped at `1 2 3`, continue names counting + 2/3 ✓ | stop→exit 0.50 s; door: only `allow api.deepseek.com:443` |
| D4 | same 4 proofs, final adapter | docker / DeepSeek / **gw** (`dk-gw-ds-*`) | all ✓ (steer `1..4` + DONE; stop `1 2`, "completed 2 of 30") | stop→exit 0.59 s |
| D5 | file mode reaches Anthropic | docker / Anthropic / file | `fail`: provider credit error (auth accepted) | door: `allow api.anthropic.com:443` only |
| P1 | provider swap: openai-responses | docker / OpenAI gpt-5-mini / gw (`dk-gw-openai.*`) | ok `4\nPINEAPPLE` | 8.7 s, $0.00186, `gateway POST /v1/responses -> 200` |
| P2 | resume, steer, stop→continue | docker / OpenAI / gw (`dk-gw-oai-*`) | ORCHID ✓; steer: DONE, count.txt empty (gpt-5-mini spends its first steps on `ls` and `: >`, so line 10 came before any number); continue names the counting and "1" | stop→exit 0.42 s |
| P3 | openai-chat | docker / DeepSeek `https://api.deepseek.com` / gw | ok `4\nPINEAPPLE`, `POST /v1/chat/completions -> 200` | 6.7 s |
| P4 | openai-chat with OpenAI gpt-5-mini | docker / gw | `fail` 400: "max_tokens not supported, use max_completion_tokens" | an @ai-sdk/openai-compatible limit; use openai-responses for OpenAI |
| S1 | late steers (after line 2 / 4 / 5 / 6 of a 1-step answer) | docker / OpenAI | 2, 4, 5 → second turn answered, steers 1/1. 6 (after the final `step_finish`) → `ok`, **steers 0 / sent 1**: idle won the race and the line never reached OpenCode | the `steers` count exposes the lost line, as designed |
| S2 | grep/glob tools in the sandbox | docker / OpenAI (`dk-grep*`) | without rg: both tools fail, door `deny github.com:443` (ripgrep download). With rg in tools: both work, no deny | — |

## Gateway vs file
Both work with no change to the folder. OpenCode reads the key itself through `{file:…}` in
`OPENCODE_CONFIG_CONTENT`, so the value is never in any environment: the config holds only the path.
The gateway's `http://hi-door-…:8080/v1` base URL is accepted for all three shapes. In gateway mode the
TLS needs no CA. In file mode, Bun (OpenCode's runtime) honoured the mounted CA bundle when going
through the door. The gateway's one request per connection did no harm: SSE streaming worked for
`/v1/messages`, `/v1/responses` and `/chat/completions`. The only gateway artefact was
`gateway error IncompleteReadError` (D2, before the fix): the adapter killed the server while the
title-generation call was still streaming. A preset session title now removes that call (1 provider
call per one-shot instead of 2).

## Secret audit (`EV/audit-{gateway,file}.json`, `oc-scripts/audit.py`; OpenAI key; probed mid-run, scanned after)
| place | gateway | file |
|---|---|---|
| `docker inspect` run / door (key; token for gw) | clean / clean | clean / clean |
| host `/proc/*/cmdline`; new host pids' environ | clean; only the 2 containerd shims¹ | same |
| every process environ in the run container (adapter, `opencode serve`) | key clean, token clean | key clean |
| workspace + `.home` (opencode.db/WAL, logs, config), run logs, tools dir | key clean, **token found nowhere** | key clean |
| `/dev/shm/hi-<sid>`, `hi-*-<sid>` containers after | gone | gone |
¹ This machine's dockerd, containerd and shells already carry `OPENAI_API_KEY` in their environment
(as foundation found for `EXT_ANTHROPIC_API_KEY`). The shims inherit it from containerd, not from hirun.
**Where OpenCode puts the token:** nowhere. It re-reads `{file:}` when it loads config and keeps the
value in memory: no `auth.json`, nothing in SQLite or the logs.
Image: hi-base is built without secrets (foundation). Audit gotcha, fixed: other agents run `hi-run-*`
containers at the same time, so the probe must select its own container (by mount), not the first `hi-run-*`.

## Findings that shaped the folder
1. **Loopback inside the hardened container works** (read-only root, cap-drop ALL, `--internal`
   network, HTTPS_PROXY set): the adapter's urllib uses `ProxyHandler({})`, and `child_env` gives
   OpenCode NO_PROXY. The server is ready in about 1–2 s. Every docker proof above went through it.
2. **ripgrep is a hidden runtime download.** OpenCode fetches `ripgrep-15.1.0-…musl.tar.gz` from
   github.com the first time grep/glob runs; in the sandbox both tools fail and the model works around
   it with `read`. The fix is in install.sh (PyPI wheel, pinned). The survey missed this, because the
   host had `rg` on PATH.
3. **Egress without the switches** (`EV/dk-noquiet.json`, a scratch copy with an empty run.sh):
   `deny models.opencode.ai` ×2 and `deny registry.npmjs.org` (the unconditional background
   `npm install @opencode-ai/plugin` into `~/.config/opencode`); run ok, 7.1 s, so harmless. With the
   switches: zero denies. `npm_config_offline=true` makes that install fail at once, because OpenCode
   uses npm's own Arborist, which reads `npm_config_*`. Locally it also keeps 29 MB of npm cache out of
   `.home` (888 KB instead). A read-only config dir would also skip it, per the source.
4. **Quiet default plugins:** `OPENCODE_DISABLE_DEFAULT_PLUGINS=1`. Claude Code compatibility (reading
   `~/.claude/CLAUDE.md` and skills) is off, so only `home/` and `files` shape the agent.
5. **Status from events:** `session.error` MessageAbortedError → stopped; any other session.error → fail,
   with the provider's message as the answer (proven by the credit errors); a stop that arrives after
   the turn already ended → `ok` (seen with gpt-5-mini: `stop requested`, status ok, count 1–30). A server
   that dies → fail (the default `on_exit`).

## Contract friction
- **Needed, not given:** nothing essential. `HI_PROVIDER_KEY_FILE` was exactly right, because OpenCode
  has native `{file:path}` substitution.
- **No public way to add an event source.** The SSE reader thread writes into `self.events` with its
  own source name ("sse"). That works because it is a plain attribute, but it is undocumented contract
  surface. Suggest documenting `self.events.put((source, line))`, or a `self.pump(iterable, name)`
  helper, in hi_adapter.
- **`finish` is overridden** to SIGTERM the server first, so its DB closes cleanly before `_reap` kills
  it. A documented `on_finish` hook would be cleaner. Nothing in `hi_adapter.py` was changed.
- **run.sh is thin.** The provider mapping is JSON (config content) and the adapter needs the
  provider id anyway, so it lives in adapter.py. "run.sh maps HI_* onto the CLI" is not always the
  natural split; I suggest the contract allow either.
- **Given, not used:** `HI_MODEL`/`HI_RESUME` (the request line carries them), `metadata`, `home/` beyond
  one config file. `instructions` go only to AGENTS.md (no prepend needed).
- **hirun's `--steer-after-lines N` depends on the model.** With gpt-5-mini, `reasoning` events and
  setup steps moved line 10 to before any number was counted. A `--steer-when 'count.txt has 3 lines'`
  trigger would make the proof provider-independent.

## Open issues
- Cost is 0 for models OpenCode's catalog lacks under that provider id (DeepSeek through `anthropic`,
  or `hi`). Declaring `cost` in `models` would need prices per request.
- openai-chat with OpenAI reasoning models fails (`max_tokens`); openai-responses is the OpenAI path.
- ripgrep is pinned for linux x86_64 only (no aarch64 wheel on PyPI). The tools hash does not include
  the CPU: the AVX2 binary is chosen at install time.
- A steer that lands after idle is dropped (`steers` < `steers_sent`); the server must re-issue it as
  a new response with the resume id.
- Provider retries (`session.status retry`) are passed on, but only `run.timeout_s` bounds them.
- Not tested: git workspaces (survey: `.git/opencode` project id, not in `git status`); `snapshot:false`
  should stop the git object store in `.home`.
