# Rebuild prototype — consolidated findings (2026-10-20)

`R` = `scratchpad/rebuild`. Sources: `R/BRIEF.md`, `R/reports/{foundation,claude-code,codex,pi,opencode,hermes}.md`,
`R/foundation/{template/,hirun.py,door.py,base.Dockerfile}`, `R/harnesses/*/`. Every claim below is traced to one of them.
The runner (`R/foundation/hirun.py`) was used unmodified by all five harness agents (some subclassed `hirun.Run` for count-based cues).

## 1. Result

All five folders reached the top tier, proven locally and in the hardened docker sandbox, with a cached read-only install and both
secret modes (gateway and file). `hi_adapter.py` stayed byte-identical in all five; no contract change was needed to get there.

**Providers.** The Anthropic key ran out of credit at ~06:36 UTC (`400 "credit balance is too low"`). Proofs before then ran on
`claude-sonnet-4-6`; later proofs on DeepSeek `deepseek-chat` (anthropic shape via `https://api.deepseek.com/anthropic`, or
openai-chat/responses) or OpenAI `gpt-5-mini`. The credit error doubled as a proof: claude-code, pi and opencode turned it into
`status: fail` with the provider's message as answer while the exit code was 0 — status from events, not exit codes.

| harness | pin | tier | shapes; which provider proved what | install miss → hit (docker); tools | stop→exit (docker) | steer (cue at count=3) | secrets | biggest open issue |
|---|---|---|---|---|---|---|---|---|
| claude-code | `@anthropic-ai/claude-code@2.1.304` (npm, native glibc binary) | steered | anthropic-messages only. **Anthropic:** everything local + docker gw; docker file one-shot/resume/steer (its stop hit the credit error). **DeepSeek:** docker gw one-shot/resume/steer; file one-shot, stop+continue | 29.5 s → 0.0 s; 276 MB | 0.30 s gw (Anthropic); 0.19 s file (DS); local 0.09 s | 1/1, count stops at 4 (one number in flight); merged into the running turn | gw + file | `cost_usd` from Claude's price table — wrong on DeepSeek; auto-memory on by default (2.1.304) |
| codex | `@openai/codex@0.163.0` (npm, native musl) | steered | openai-responses only. **OpenAI:** everything, local + docker gw + file. **DeepSeek** `/v1/responses`: docker gw one-shot + steer; file resume | 11.7 s → 0.16 s; 411 MB | 0.28 s gw / 0.27 s file; local 0.07 s | 1/1, count 3; plus early steer (before turn id) and steer/turn-end race (stub) proven | gw + file | a steer arriving after `turn/completed` is lost (`steers < steers_sent`); no model metadata for gpt-5-mini / deepseek-chat |
| pi | `@earendil-works/pi-coding-agent@1.3.0` (npm) | steered | all 3 shapes. **Anthropic:** local one-shot + resume only. **DeepSeek:** anthropic shape for everything docker gw+file; openai-chat resume (gw+file), steer (gw). **OpenAI:** responses (local + docker gw), chat (local) | 15.1 s → 0.14 s; 154 MB | 0.21–0.24 s gw/file; local 0.06 s | 1/1, count 3; lands only after the whole current tool batch (latency follows the model's batching) | gw + file | idle steer (`disposition: started`) untested end to end; cost null outside pi's catalog; Anthropic in docker unproven |
| opencode | `opencode-ai@1.19.3` (npm, Bun binary) + ripgrep 15.1.0 (PyPI wheel, sha256) | steered | all 3 shapes. **Anthropic:** everything local + docker gw; file mode reached Anthropic (credit fail). **DeepSeek** anthropic shape: everything docker gw+file; openai-chat docker gw one-shot. **OpenAI:** responses, everything docker gw. openai-chat on gpt-5-mini **fails** (`max_tokens`) | 13.8 s → 0.15 s; 204 MB | 0.33 s gw (Anthropic); 0.50 s file / 0.59 s gw (DS); local 0.11 s | 1/1, count 3–4; late steer after the final `step_finish`: **0/1** (lost, made visible by `steers`) | gw + file | late steer lost; cost 0 outside catalog; ripgrep is x86_64-only and the tools hash ignores CPU |
| hermes | `hermes-agent[anthropic,acp]==0.19.0` (uv, `--exclude-newer 2026-10-19`) | steered | anthropic-messages (openai-chat worked in a scratch variant, not shipped). **Anthropic:** local one-shot, resume, stale-URL demo. **DeepSeek:** the whole final suite, local + docker gw + docker file | 12.9 s → 0.2 s; 205 MB | 1.48 s gw / 1.82 s file; local 1.13 s | 1/1, count 3, via `/steer` | gw + file | resume under the gateway needs `repoint()` (writes hermes's `state.db`) because the gateway URL changes per response; in file mode the key is in hermes's environ |

Foundation stand-in (`R/foundation/prove.py`, 19/19 PASS): SIGINT stop 0.45 s docker / 0.39 s local; kill after `stop_timeout_s`
2.2 s; hard-kill early `HI_OUTPUT` held `{running, resume}` and resume continued exactly; template install miss 2.2–8.8 s / hit
0.2 s; teardown 0 leftovers.

## 2. The minimal contract, as proven

### harness.json (closed schema — unknown/missing fields are errors; `hirun.py Folder.validate`)
| field | final form | evidence it is needed |
|---|---|---|
| `name` | `[a-z0-9-]+`; names `tools/<name>-<hash>` | all five |
| `description` | one line | all five |
| `provider` | `{url, api}` default; `api` ∈ `apis`; `url` per the definition below | all five; codex's default `https://api.openai.com/v1` |
| `apis` | subset of `anthropic-messages`, `openai-responses`, `openai-chat` | pi, opencode: 3; claude-code, codex, hermes: 1 |
| `install` | `{egress: [host…], timeout_s}` | npm only (claude-code, codex, pi), npm + pypi (opencode), pypi (hermes) |
| `files` | `{workspace-relative path: template}`, `{instructions}` substituted | all five, one entry each, every one under `.home/` (§3) |
| `run` | `{interrupt, stdout, timeout_s, stop_timeout_s}` | all five: `steered`, `application/x-ndjson`, timeout 900–1800 s, stop 15–20 s (> adapter grace 10–15 s) |

Cut from v0 by the foundation and missed by no harness: `sandbox` (one base image), `run.argv` (always `bash run.sh`), `run.env`
(run.sh holds it). Never exercised by a real harness: `run.interrupt` `continued`/`responded`, `run.stdout` `text/plain` — keep the
first two (they are the server's degradation tiers for future CLIs), consider cutting `text/plain`.

### What a harness is given
| item | value | used by (evidence) | verdict |
|---|---|---|---|
| `HI_WORKSPACE` | cwd; same path inside and out | every run.sh `cd`s to it; codex `thread/start{cwd}`, opencode `PWD` | keep |
| `HOME` | `$HI_WORKSPACE/.home`, persists across responses | all five keep CLI state, settings and instructions there | keep |
| `HI_HARNESS_DIR` | the folder, ro | every run.sh `exec python3 -u $HI_HARNESS_DIR/adapter.py` | keep |
| `HI_OUTPUT` | per-run dir **outside** the workspace | hi_adapter `Output` | keep |
| `HI_PROVIDER_URL` | see definition below | all five | keep |
| `HI_PROVIDER_API` | the shape | codex (asserts it), pi (provider/api mapping), opencode (provider id); not needed by claude-code/hermes (one shape each) | keep |
| `HI_PROVIDER_KEY_FILE` | ro file: key (file mode) or per-session token (gateway) | claude-code `apiKeyHelper: cat`, pi `apiKey: "!cat …"`, opencode `{file:…}`, codex `provider_key()` → `account/login/start`, hermes `provider_key()` → `ANTHROPIC_API_KEY` in hermes's env only | keep |
| `HI_MODEL` | request model | claude-code run.sh (maps haiku/small-fast model to it), hermes `config.yaml` `${HI_MODEL}` (adapter re-exports); shell/config can only read env | keep, as the **only** model channel |
| `PATH` | `$HI_TOOLS/bin:` + system | all five | keep |
| `HTTPS_PROXY`/`NO_PROXY` (+lowercase) | door; `127.0.0.1,localhost,<door>` | file mode: every CLI CONNECTs through it; opencode loopback server and the gateway need NO_PROXY | keep |
| CA vars (`SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`, …) | `/etc/hi/ca.pem` when egress re-signs TLS | file mode on this machine only; gateway needs none | runner-side, machine-specific |
| stdin line 1 | compact JSON `{task, instructions, model, resume, metadata}` | `task` and `resume`: all five | keep `task`, `resume` |
| later stdin lines | one JSON string each = a steer | all five (steered) | keep |
| `home/` | copied into `$HOME` before every response | claude `settings.json`, codex `config.toml`, opencode `opencode.json`, hermes `config.yaml`; pi none (rewrites `models.json` each response) | keep |
| mounts | workspace rw; folder, tools, key file ro; rundir rw; `/tmp` tmpfs 512 MB; root ro | all five | keep |

**v0 items no harness used — candidates to cut:**
| item | used? | recommendation |
|---|---|---|
| `HI_TASK`, `HI_REQUEST` | cut by foundation; missed by no one | stay cut (request lives on line 1) |
| `HI_RESUME` env | no adapter read it; all five read line-1 `resume` (claude-code, pi, hermes explicitly) | **cut**; also drop the env fallback in `read_request` |
| line-1 `model` | duplicates `HI_MODEL`; adapters read `request["model"]` | **cut from line 1**; `read_request` fills `request["model"]` from `HI_MODEL` (one channel, which env-only consumers need) |
| line-1 `instructions` | no adapter read it; all five route `{instructions}` through `files` into a global file under `.home` | **cut from line 1**; `files` is the one channel. A CLI without a global file targets e.g. `.home/.hi/instructions.md` and its adapter prepends it |
| `metadata` | unused by all five; always `{}` | **cut** |
| `HI_TOOLS` at run time | used only via `PATH` (codex, pi, hermes, claude-code said so) | keep for install.sh (all five use it), **drop from the run env** |
| `HI_PROVIDER_API` | used by 3 of 5 | **keep** (v0 cut candidate disproven) |
| `HI_PROVIDER_KEY` (env, option a) | template only | **cut** — never the key's value as env (§5) |
| request `files` | dropped from line 1; never exercised by the runner | keep as a runner-side write before the response; untested |

### What it gives back
- **stdout**: NDJSON. All five pass the CLI's events through unchanged and add `hi.*` events (`hi.stop`, hermes `hi.replayed`,
  `hi.text` for non-JSON lines); opencode re-emits SSE parts in `opencode run --format json` shapes.
- **stderr**: free text (hermes INFO logs, claude `unrecognized_model`, codex bubblewrap `configWarning`).
- **workspace changes**: the diff outside `.home`. With instructions under `.home`, `files_changed` stayed the user's (pi row 16: empty).
- **`$HI_OUTPUT`** = `{answer, status, resume, usage, cost_usd, steers}`, `status ∈ running|ok|fail|stopped`, written atomically
  (tmp + fsync + rename) early (as soon as `resume` is known) and at the end. The runner maps a cut-off `running` to `stopped` if it
  asked for a stop and a resume id exists, else `fail`. Exit code never read as status. Early resume: claude-code and pi choose it up
  front (uuid); codex after `thread/start`; opencode after `POST /session`; hermes after `session/new`.
- **`usage` is not uniform today**: claude-code Anthropic-raw (`input_tokens`, `cache_creation_input_tokens`, …), codex camelCase
  (`inputTokens`, `cachedInputTokens`, …), pi/opencode/hermes `input_tokens/output_tokens/cache_read_tokens/cache_write_tokens`
  (+`reasoning_tokens`). **Pin** `{input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens}` per
  response (others allowed); two adapters then map.
- **`cost_usd`**: claude-code wrong on DeepSeek; codex always null; pi null outside its catalog; opencode 0 outside its catalog;
  hermes null when its own price is unknown → cost belongs to the server/gateway (§6); the adapter's value is advisory.

### Control
- stdin stays open in every mode. **EOF = graceful stop** (implemented in hi_adapter; **no proof used it** — every stop was SIGINT).
- **SIGINT** = `docker kill --signal INT` → `--init` tini with `TINI_KILL_PROCESS_GROUP=1` → run.sh's group (run.sh `exec`s the
  adapter); the CLI runs in its own session, so only the adapter sees it and uses the CLI's own stop. Kill after
  `run.stop_timeout_s`; hi_adapter finishes `stopped` after `stop_grace_s` and SIGKILLs the CLI groups in `_reap`.
  `run.timeout_s` → SIGINT → kill.
- **`HI_PROVIDER_URL` definition** (asked by codex and pi): the base URL the shape's **official SDK** takes —
  `anthropic-messages`: `https://api.anthropic.com`, `https://api.deepseek.com/anthropic` (no `/v1`; the SDK appends
  `/v1/messages`); `openai-*`: `https://api.openai.com/v1`, `https://api.deepseek.com/v1` (with the version path). The runner
  validates it; adapters don't guess. (Today pi strips/appends `/v1` to a bare host, opencode appends `/v1`, claude-code/hermes strip
  `/v1`; codex 404s on a bare host — the guessing in pi/opencode must be replaced by this rule.) Under the gateway the same path
  follows `http://<gateway>:8080`.
- **Stale `files`** (claude-code, codex, pi, hermes all hit it): `prepare` skips an empty render, so a response without instructions
  kept the previous `CLAUDE.md` (proven: claude answered "6\n\nPAPAYA"). **Rule:** every response renders every `files` target; an
  empty render **deletes** the target. `home/` stays an additive copy that overwrites what it ships.
- **`steers`** = the number of steer lines the CLI **acknowledged**, in order (claude-code: the user line's `isReplay` echo; codex:
  `turn/steer` result or a queued `turn/start`; pi: `disposition` `queued|started`; opencode: `user` message event; hermes: `/steer`
  ack). After a stop starts, hi_adapter drops steer lines. If `steers < steers_sent`, the last `steers_sent − steers` lines were not
  delivered (opencode S1 proved this; codex's design has it). **The server** re-sends them in order, joined, as a new response with
  `resume = output.resume` (the `continued` path) when status is `ok`; if `stopped`/`fail` it reports them undelivered. It never sends
  a steer after it asked for a stop.

## 3. The folder template

```
<name>/  harness.json  install.sh  run.sh  adapter.py  hi_adapter.py  home/   (+ template-only standin.py)
```
- **harness.json** §2. **install.sh**: pinned CLI into `$HI_TOOLS`, binaries in `$HI_TOOLS/bin`, assert the version; pin anything
  else it fetches inside itself (hermes `--exclude-newer`, opencode rg `--require-hashes`, template standin sha256), because only
  install.sh is hashed. **run.sh**: `cd $HI_WORKSPACE`, CLI-native env (base URL, quiet switches, `PYTHONDONTWRITEBYTECODE=1`),
  `exec python3 -u $HI_HARNESS_DIR/adapter.py`; mapping may live in the adapter when it is JSON or per-request (pi `models.json`,
  opencode `OPENCODE_CONFIG_CONTENT`, codex `-c` + RPC login) — the contract allows either. **adapter.py** 97 / 174 / 166 / 230 /
  203 lines (claude-code / codex / pi / opencode / hermes). **home/**: static CLI settings.
- **hi_adapter.py** (194 lines, stdlib, py ≥ 3.9): `Output` (atomic, field/status checked), `read_request` (line 1, tolerates pretty
  JSON), `provider_key()`, `child_env()` (loopback never proxied), `Adapter` — one event-queue loop over CLI lines, stdin steers, EOF
  and SIGINT/SIGTERM; `spawn` (own session, pump thread, `:exit` event), `emit`, `accepted_steer`, `finish`, default `on_exit`
  (unfinished → `fail`/`stopped`), stop grace, `_reap` (close stdin, wait 3 s, `killpg` SIGKILL); an adapter exception becomes
  `fail`. **DRY** by byte-identical copy — a runtime-injected library would become contract surface and a folder would no longer run
  alone — enforced three ways: unit test over every folder, `hirun.py check`, `hirun.py run` refuses a drifted copy.
- **Additions the reports asked for** (all backwards-compatible; change every copy in one commit):
  1. **JSON-RPC helper** (`send`, `call(method, params, then)`, id→callback dispatch, answering server requests) — codex and hermes
     each wrote ~15 identical lines; every app-server/ACP adapter will need it.
  2. **Extra event sources**: a public `self.pump(iterable, name)` — opencode's SSE thread writes `self.events.put(("sse", …))`,
     undocumented surface.
  3. **`on_finish` hook** before `_reap` — opencode overrides `finish` to SIGTERM `opencode serve` so its DB closes cleanly.
  4. **`stopping` property** — pi, claude-code, codex, hermes, opencode all read `self.stopping_since` to tell a stop from an error.
  5. **`PYTHONDONTWRITEBYTECODE=1`** in the template run.sh — local runs wrote `__pycache__` into the folder (`template/__pycache__`
     exists today); codex, pi, hermes added it.
  6. The template's default `files` target `AGENTS.md` (in the workspace) should become a `.home/…` path — all five moved theirs.
- **Adapter patterns and their done/stop conditions:**
| harness | pattern | task / steer | done | stop |
|---|---|---|---|---|
| claude-code | P1 stream-json: `claude -p --input-format/--output-format stream-json --replay-user-messages --session-id|--resume` | `user` lines (steer merges into the running turn or becomes the next turn) | `result` with replays ≥ lines sent | `control_request` interrupt → next `result` → `stopped` |
| codex | P2 `codex app-server` JSON-RPC | `turn/start`; `turn/steer{expectedTurnId}`; steer before turn id or refused → queued → next turn | `turn/completed` for our turn, nothing queued/in flight | `turn/interrupt` → `turn/completed` `interrupted` |
| pi | `pi --mode rpc` | `prompt`; `prompt{streamingBehavior:"steer"}` | `agent_settled` and no steer outstanding, empty `queue_update` | `clear_queue` then `abort` |
| opencode | P4 local HTTP server + SSE: `opencode serve --port 0 --hostname 127.0.0.1`, basic auth | `POST /session` (title preset: one call fewer), `prompt_async`; steer = another `prompt_async` | `session.status` idle, every prompt became a user message, last assistant newer | `POST /abort` → `MessageAbortedError` |
| hermes | P3 ACP: `hermes acp` | `session/new|load`, `session/prompt`; steer = `session/prompt "/steer …"` (a late ack is re-sent as the next prompt) | main prompt's result then settle | `session/cancel` (both −32603 and `cancelled` = stopped); hermes ignores SIGINT |
  Non-interactive prompts answered so a run can never hang: claude-code `--dangerously-skip-permissions` + `IS_SANDBOX=1`; codex
  `approvalPolicy never`, `danger-full-access` (bwrap can't run in the container), approvals accepted; opencode permission `once`,
  `question` rejected; hermes `HERMES_YOLO_MODE`, `allow_once`; pi has no permission system.
- **Where instructions go** (always under `.home`; never overwrite the user's AGENTS.md/CLAUDE.md):
  claude-code `.home/.claude/CLAUDE.md` (code-word test: workspace AGENTS.md is ignored once a workspace CLAUDE.md exists; the home file
  is always read); codex `.home/.codex/AGENTS.md` (`CODEX_HOME=$HOME/.codex`); pi `.home/.pi/agent/AGENTS.md` (pi loads both; the
  user's AGENTS.md was untouched, `files_changed` empty); opencode `.home/.config/opencode/AGENTS.md` (`OPENCODE_DISABLE_CLAUDE_CODE=1`
  so only home/ + files shape it); hermes `.home/.hermes/SOUL.md` (hermes loads only one of `.hermes.md`/AGENTS.md/CLAUDE.md).

## 4. Sandbox and install

- **Base image** `hi-base:80d60e8c2bde`, **405 MB**: `python:3.12.15-slim-trixie` + node 22.23.3 + npm (from
  `node:22.23.3-bookworm-slim`) + uv 0.9.5 + git + ca-certificates, user `hi` 1000:1000, `UV_PYTHON_DOWNLOADS=never`, `UV_NO_CACHE=1`;
  no https fetch at build; tag = Dockerfile hash. Layers: python 119, node 125, git+perl 99, uv 51, npm 11 MB. No tini (docker
  `--init` supplies it; a non-Docker runtime adds `tini -g`, 1 MB). git: no harness proof needed it (git workspaces untested);
  dropping it saves 99 MB.
- **Install container**: `--init`, HARDENING, uid 1000, its own `--internal` network + a door allowing only `install.egress`, no DNS,
  `HOME=/tmp`, folder ro, tools dir rw **at its final path** (npm/uv write absolute paths), no provider vars or secrets (so env values
  may be on argv). Cache key `tools/<name>-sha256(install.sh ‖ \0 ‖ base image id)[:12]`; complete only when `.hi-installed` is written
  last; a failed or timed-out install deletes the dir; one `flock` per dir. Proven: registry.npmjs.org 200; api.anthropic.com,
  pypi.org, github.com 403. Timings in §1. **Gap: the key lacks arch/CPU** (opencode picks the AVX2 binary at install time; ripgrep is
  x86_64-only) — add the arch.
- **Session container**: `docker run --rm -i --init -e TINI_KILL_PROCESS_GROUP=1`, HARDENING = `--cap-drop ALL --security-opt
  no-new-privileges --read-only --tmpfs /tmp:rw,exec,nosuid,nodev,size=512m --pids-limit 512 --memory 4g`, `--user 1000:1000`;
  workspace, folder (ro), tools (ro) and rundir at **the same paths** as the host; key file ro; CA ro; `-w` workspace; env passed **by
  name only** (`-e NAME`, values live in the docker client's allowlisted environ). A per-session `--internal` network; the door container
  (LOCKDOWN, uid 65534, `python:3.12-alpine`) is the only member also on the bridge. File mode: CONNECT allowlist = the provider host.
  Gateway mode: allowlist empty, the door also serves the gateway on :8080. Proven: DNS fails; 1.1.1.1 and docker host 172.17.0.1
  unreachable; other hosts 403; loopback servers inside the container work (opencode `serve`; the `NO_PROXY` loopback rule). Docker
  adds ~1–2 s per response (door container ~1 s).
- **What each harness tried to reach** (provider-only door) and the switch that quiets it:
| harness | denied at the door without the switch | switch | harm if blocked |
|---|---|---|---|
| claude-code | api.anthropic.com ×2 (non-essential traffic) | `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1` | none |
| codex | github.com, api.github.com, chatgpt.com (plugins, model discovery) | `features.plugins=false`, `features.api_key_model_discovery=false`, `analytics.enabled=false`, `check_for_update_on_startup=false`; plus `unbounded_connection_retries=false` (a dead provider fails in 24.6 s, not at timeout) | none |
| pi | pi.dev ×3 (catalog, version, telemetry) | `PI_OFFLINE=1 PI_TELEMETRY=0 PI_SKIP_VERSION_CHECK=1` | none |
| opencode | models.opencode.ai ×2; registry.npmjs.org (background plugin install); **github.com (ripgrep download)** | `OPENCODE_DISABLE_{MODELS_FETCH,AUTOUPDATE,LSP_DOWNLOAD,DEFAULT_PLUGINS,CLAUDE_CODE,EMBEDDED_WEB_UI}=1`, `npm_config_offline=true`; **rg moved into install.sh** | **grep/glob tools broken** without rg |
| hermes | models.dev; github.com (tirith); openrouter.ai (metadata); **api.anthropic.com/v1/models with the key, ignoring the base URL** (in file mode on DeepSeek it would have sent the DeepSeek key to Anthropic — only the door's deny stopped it) | `TIRITH_ENABLED=0` + `security.tirith_enabled:false`; `context_length: 128000`; `model.base_url: ${ANTHROPIC_BASE_URL}` | none after the fix; ~16 local-server sniffing GETs to the provider URL remain (harmless) |
  Rule: the door's deny log is the detector for hidden runtime downloads; a deny that breaks a tool moves into install.sh; a
  provider-only door is also a key-exfiltration barrier (hermes).
- **Teardown**: `docker rm -f` run + door, `network rm`, overwrite-with-zeros + unlink the key file, rmdir `/dev/shm/hi-<sid>`. Proven:
  0 `hi-*` containers/networks/shm dirs after every run by every agent. `hirun.py clean` sweeps crash leftovers.

## 5. Secrets

- **Options tested** (foundation matrix, stand-in + a real Anthropic call):
| where the key was found | (a) env by name | (b) 0400 tmpfs file | (c) gateway |
|---|---|---|---|
| `docker inspect` | **yes** | no | no |
| host `/proc/*/environ` | **yes** (client, docker-init, adapter, CLI) | no | no |
| readable by the model's shell | **yes** | **yes** | **no** (only the token is visible) |
| host `ps`, image, tools, workspace, logs | no | no | no |
  All five harnesses passed (b) and (c) with **the same folder**; their audits found the key in none of: `docker inspect` (run, door),
  host `ps`, host environ of the hirun tree, environ inside the container (except hermes in file mode, by design), image, tools dirs,
  workspaces + `.home`, run logs, install logs. Where each CLI keeps what it is given: claude-code memory (`apiKeyHelper`); codex
  app-server memory (RPC login, `cli_auth_credentials_store="ephemeral"`, no `auth.json`); pi `models.json` holds only the path;
  opencode `{file:}` path only, nothing in SQLite or logs; hermes `auth.json` holds a sha256 fingerprint only. The gateway token was
  found on disk nowhere.
- **Recommendation: (c) gateway in the egress door; (b) key file as fallback; never (a).** The door also runs a plain-HTTP reverse
  proxy to the one provider: it refuses anything but the session token (401), strips auth/hop headers, adds the real key per shape
  (`x-api-key` or `Authorization: Bearer`), forwards over TLS. The key reaches the door **on its stdin only**. Harness code is identical
  in both modes (read `HI_PROVIDER_KEY_FILE`, send its contents to `HI_PROVIDER_URL`). Extra wins: the model's shell can never read the
  key; CLIs that persist credentials persist a token; model calls need no CA bundle; usage is observable at one point. Proven through
  it: SSE on `/v1/messages`, `/v1/responses`, `/v1/chat/completions`; `http://` bases accepted by all five.
- **Limits:** HTTP/1.1, one request per connection (`Connection: close`) — a TLS handshake per call (~0.1–0.2 s); CLIs that keep idle
  sockets log a harmless `IncompleteReadError` (pi, claude-code on a stop). No WebSocket upgrade (no harness needed one). Auth header
  chosen by shape only — a provider wanting another header, or a CLI that refuses `http://` or ignores base URLs, needs (b).
  **502-after-200 bug** (`door.py` `Gateway.handle`): after response headers are relayed, an upstream `SSLError` (DeepSeek closing TLS
  without close_notify) makes the handler write `HTTP/1.1 502` into the started body — fix: once headers are sent, only close.
  **URL changes per response** (`http://hi-door-<sid>:8080`, a new local port in local mode): hermes stores the base URL per session in
  `state.db`, so resume hit a dead door (proven: fail after 25 s) and needs `repoint()`, a write into the CLI's private DB. **Fix: a
  stable gateway URL for the whole session** (e.g. a network alias `http://hi-provider:8080/<path>`, identical in every session network);
  likewise a stable key-file path (e.g. `/run/hi/key` — pi writes it into `models.json`). **Cost on swapped providers**: the CLIs' price
  tables assume their default provider (§2); the gateway sees every `usage` and should own cost. **(b)'s limits**: the model's shell can
  `cat` the key; it's in hermes's environ (hermes needs `ANTHROPIC_API_KEY`); it lies in the door's CONNECT path to the real host.
- **Host environment leak**: this machine's shells, dockerd and containerd carry `EXT_ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY` and
  `OPENAI_API_KEY` (containerd shims inherit them — opencode audit). The foundation's first denylist (`CLAUDE*`, `ANTHROPIC*`, …) passed
  `EXT_ANTHROPIC_API_KEY` to every docker client, and hermes's first audit script leaked `DEEPSEEK_API_KEY` into hirun the same way.
  **Rule: child environments are an allowlist of variable names, never a blocklist** (hirun `PASS_ENV`: PATH, HOME, LANG, LC_*, TERM,
  TZ, USER, LOGNAME, proxy, CA, DOCKER_*). Corollary for production: the container daemon itself must run without provider keys in its
  environ.

## 6. Server requirements derived (build order)

1. **Folder loader**: closed-schema validation (§2); `hi_adapter.py` identity check; refuse folders whose `provider.url` breaks the URL
   definition. *Evidence: `Folder.validate`, drift refusal.*
2. **Base image**: pinned inputs, tag = Dockerfile hash, image id recorded. *`hi-base:80d60e8c2bde`.*
3. **Tools cache**: install container + per-install door (`install.egress`), no secrets, key = install.sh + base id + **arch**,
   completion marker, delete on failure, per-key lock, read-only mount at the same path. *§4; five misses 11.7–29.5 s, hits
   0.0–0.2 s; opencode arch gap.*
4. **Allowlisted environment** for every child (docker client, door, harness). *§5 host leak.*
5. **Per-session network + door**: CONNECT allowlist = provider only; **gateway** with a **stable per-session URL** (alias) and token
   check; key via stdin; 502-after-200 fix; start the door in parallel with workspace prep (~1 s). *§5, hermes resume, codex SSLError.*
6. **Credential file**: per-session token (or key in fallback), tmpfs, 0400, owned by uid 1000, ro mount at a stable path,
   overwrite + unlink at teardown.
7. **Workspace prep per response**: copy `home/` into `.home`; render `files`, **deleting empty renders**; write request files; chown to
   1000; snapshot for the diff (outside `.home`); workspace root not under `/tmp` (codex skips its helper binaries there). *Stale-files
   friction in 4 reports; codex warning.*
8. **Process execution** (async, one per response): `docker run` flags of §4, env by name; write line 1 `{task, resume}`, keep stdin
   open, write steer lines; stop = SIGINT + `stop_timeout_s` timer → kill; `run.timeout_s` → stop; stream stdout/stderr to the record.
   *Stop→exit 0.06–1.82 s across five; stubborn kill 2.2 s.*
9. **Result collection**: read `HI_OUTPUT` (early version during the run); status mapping for a cut-off run; never the exit code;
   `steers` vs `steers_sent`; files_changed. *Credit-error runs, hard-kill proof.*
10. **Usage normalisation and cost** at the gateway: parse `usage` from JSON/SSE responses per shape, a per-provider price table;
    adapter `cost_usd` advisory. *§2 cost row.*
11. **Session layer**: one response at a time per workspace; persist `resume`; `steered` = write the line; `continued`/`responded` =
    stop then a new response with/without resume; undelivered steers → a `continued` response; resume after `stopped`. *Stop + continue
    proofs in all five; opencode S1.*
12. **Teardown and crash sweep** (names `hi-*-<sid>`), and `.home` retention (codex grows `.home/.codex` 4–5 MB per conversation;
    claude-code auto-memory and hermes `state.db` grow too).

## 7. Open issues and next proofs

- **Anthropic in docker after 06:36**: proven before the cutoff for claude-code (everything in gw) and opencode (everything in gw);
  **not** for pi (Anthropic in docker at all), hermes (Sonnet steer/stop in docker), claude-code file-mode stop+continue (proven on
  DeepSeek). Next: re-run each folder's suite on Anthropic in docker, gw + file, once credit is restored.
- **Steer after idle, end to end**: pi `disposition: started`, claude-code's second turn for a late steer (survey only), hermes's
  re-sent late `/steer` (possible duplicate injection, from reading the source); codex and opencode lose it by design. Next: a
  server-side proof that re-sends untaken steers as `continued`, plus a runner cue on a file condition (`--steer-when`), not line counts
  — three agents had to subclass `hirun.Run` to steer at count=3.
- **EOF as stop**: implemented in hi_adapter, never exercised.
- **Cost for non-catalog models**: wrong/null/0 in every harness. Next: gateway-side usage + price table, compared with the CLIs'
  numbers on Anthropic/OpenAI.
- **`continued` / `responded` tiers** with a real CLI: all five are `steered`. Next: force one folder to `continued` and prove stop →
  resume-with-text.
- **Request `files`**: never passed by hirun. **Git workspaces**: untested (opencode `.git/opencode` project id, `snapshot:false`; base
  image git). **MCP / skills / hooks**: not exercised in the rebuild (codex hooks need `--dangerously-bypass-hook-trust`).
- **hermes openai-chat**: worked in a scratch variant (`provider: custom`, `api_mode: chat_completions`), not shipped. **codex model
  metadata** for gpt-5-mini / deepseek-chat (`model_catalog_json`) untested. **opencode openai-chat with OpenAI reasoning models** fails
  (`max_tokens`) — use openai-responses for OpenAI.
- **arm64 / musl**: every tools dir is x86_64 glibc (claude-code would double to >550 MB if both were cached).
- **Folder/contract changes to make next**: pin `HI_PROVIDER_URL` and delete URL guessing in pi/opencode; delete empty `files` renders;
  cut `HI_RESUME`, `metadata`, line-1 `model`/`instructions`, run-time `HI_TOOLS`; pin `usage` keys and map them in claude-code and
  codex; add the hi_adapter extras (§3); stable gateway URL and key path, then remove hermes's `repoint()`; fix the gateway's
  502-after-200; add arch to the tools key; decide on claude-code auto-memory (`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, untested); a model
  context-size field (hermes guessed 128000; without a value it probes for ~6 s and calls openrouter.ai).
