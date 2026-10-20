# Stage 2 report: codex (OpenAI Codex CLI 0.163.0)

`R` = `scratchpad/rebuild`, `E` = `scratchpad/codex-stage2` (proof driver + every result JSON). All run 2026-10-20.

**Verdict: works; tier `steered`, proven local and in the docker sandbox, with both `--secret gateway`
and `--secret file`, on OpenAI (gpt-5-mini) and DeepSeek (deepseek-chat via /v1/responses).**
No key anywhere it must not be. `hi_adapter.py` used unchanged (byte-identical, `hirun.py check` ok).
`@openai/codex@0.163.0` is still npm `latest` (checked 2026-10-20; `alpha` is 0.164.0-alpha.6).

## The folder `R/harnesses/codex/`
| file | what it does |
|---|---|
| `harness.json` | provider `https://api.openai.com/v1` / `openai-responses` (the only shape); install egress `registry.npmjs.org`; `files: {".home/.codex/AGENTS.md": "{instructions}"}` (global instructions, never the user's AGENTS.md); `run.interrupt: steered`, ndjson, timeout 900, stop 15 |
| `install.sh` | `npm i -g --prefix $HI_TOOLS @openai/codex@0.163.0`, asserts `codex --version`. Tools dir 411 MB (284 MB native musl binary + 71 MB code-mode host) |
| `run.sh` | `CODEX_HOME=$HOME/.codex`, mkdir, `PYTHONDONTWRITEBYTECODE=1`, exec adapter. No key, no URL here |
| `home/.codex/config.toml` | custom provider `hi` (`wire_api="responses"`, `requires_openai_auth=true`), `cli_auth_credentials_store="ephemeral"`, the 3 network-off settings (`features.plugins=false`, `features.api_key_model_discovery=false`, `analytics.enabled=false`), plus `features.unbounded_connection_retries=false`, `check_for_update_on_startup=false` |
| `adapter.py` (174 lines) | `codex app-server -c model_providers.hi.base_url="$HI_PROVIDER_URL"`; callback JSON-RPC over the hi_adapter loop: `initialize{experimentalApi}` → `initialized` → `account/login/start{apiKey: provider_key()}` → `thread/start\|resume {cwd, approvalPolicy:"never", sandbox:"danger-full-access", model}` → resume id written → `turn/start`. Steer = `turn/steer{threadId, expectedTurnId, input}`; before the turn id or refused ("no active turn") → queued, started as the next turn. Stop = `turn/interrupt`. Done = `turn/completed` for our turn, no steer queued or in flight. Usage = `thread/tokenUsage/updated.total` minus the total before our first turn. Server approval requests answered accept. Every app-server line passed to stdout |
| `hi_adapter.py` | the template's copy, unchanged |

Why `danger-full-access`: codex's own sandbox (bwrap) cannot create namespaces in our container (survey:
ENOSPC); the container is the sandbox. It still emits a harmless `configWarning` "could not find bubblewrap".

## Evidence (commands: `python3 E/prove_codex.py MODE SECRET PROVIDER [--at N --stop]`; it is hirun.Run plus a watcher that steers/SIGINTs when count.txt reaches N)
| proof | mode / secret | result |
|---|---|---|
| install miss → hit (docker) | install container | 11.7 s miss (door: only `allow registry.npmjs.org`) → 0.16 s hit; local 8.8 s → 0.12 s |
| one-shot + instructions | local gw | ok "ParisGLOBAL-ALPHA", 11.0 s, 126 stdout lines, files_changed none |
| one-shot + instructions | docker gw / file | ok "The capital of France is Paris.\n\nGLOBAL-ALPHA", 6.3 s / 5.4 s, 11.9k tokens |
| resume ORCHID | local gw | run 1 "OK" 3.7 s; run 2 (`--resume <thread>`) "ORCHID" 3.9 s, same thread id |
| resume ORCHID | docker gw / file | "OK" → "ORCHID" / "OK" → "ORCHID" (4.0–4.8 s each) |
| steer at count=3 | local gw | ok, steers 1/1, steer at 18.9 s, count final **3**, done.txt=DONE, 30.5 s |
| steer at count=3 | docker gw / file | ok, steers 1/1, count final **3**, DONE; 28.0 s / 33.7 s |
| SIGINT stop at 3 → continue | local gw | `stopped`, stop→exit **0.07 s**, rc 0; resumed: "…wrote 1 and 2 before the run was aborted while starting the command for 3" |
| SIGINT (tini) stop → continue | docker gw / file | `stopped`, **0.28 s / 0.27 s**, rc 0, count stays 3; resumed: "…successfully wrote 1 and 2 (the third append had started but was aborted)" (both) |
| SIGINT stop at 6 (audit runs) | docker gw / file | `stopped` in 1.19 s / 0.25 s, count stays 6 |
| early steer (before turn id) | local gw | `--steer-after-lines 1`: queued, sent as turn/steer once the turn id came; "apple, banana, orange KIWI-77", steers 1 |
| steer/turn-end race | stub app-server (`E/stub/race_test.py`) | turn/completed then -32600 "no active turn to steer" → queued → next turn: ok, steers 1, answer from turn 2. PASS |
| dead provider | local file, URL `https://127.0.0.1:9/v1` | `error` "Reconnecting… 1/5…5/5" then `turn/completed failed` → status **fail** "turn failed: Connection failed…" in 24.6 s (without `unbounded_connection_retries=false` it retries until the run timeout) |
| provider swap DeepSeek | docker gw | one-shot ok "…Paris.\n\nGLOBAL-ALPHA" 3.1 s; steer at 3 → count 3, DONE, 17.8 s |
| provider swap DeepSeek | docker file | ORCHID resume ok ("ORCHID."), door `allow api.deepseek.com:443` |

Event types seen (one-shot): `item/reasoning/summaryTextDelta` 97, `item/agentMessage/delta`, our 4 replies,
`item/started|completed`, `thread/started`, `turn/started|completed`, `thread/tokenUsage/updated`,
`thread/status/changed`, `account/login/completed`, `account/updated`, `account/rateLimits/updated`,
`thread/readState/changed`, `remoteControl/status/changed{status:"disabled"}`, `configWarning` (bubblewrap),
`warning` ("Model metadata for `gpt-5-mini` not found" — also for deepseek-chat). Interrupt: `turn/completed`
status `interrupted`. Usage on resume: run 2 update 1 = run 1's total (11779, turnId of run 1) → base; run 2 = 11892.

## Egress
- With our config, every docker run's door log is only the provider: 26 × `gateway POST /v1/responses -> 200`,
  18 × `allow api.openai.com:443`, 2 × `allow api.deepseek.com:443`, **0 denies**.
- Variant without the network-off block (`E/netdefault/`): tries `github.com`, `api.github.com`, `chatgpt.com`
  (all denied); the one-shot still passed in 4.1 s, so blocking does not hurt a one-shot (the survey saw a 103 MB
  plugins clone and chatgpt model discovery when open). Keep the settings: quieter door, no wasted connects.
- Container processes during a run: tini, adapter, node launcher, native `codex app-server`; no daemon
  (`daemon_auto_start` did not start one under app-server).

## Secret audit (`E/audit_live.sh`, `E/audit-live.txt`; greps never print the key)
| where | gateway | file |
|---|---|---|
| `docker inspect` run / door (live) | clean / clean | clean / clean |
| host `/proc/*/cmdline` | clean | clean |
| host procs of this run (environ has this run's HI_OUTPUT: docker client, adapter, codex, shells): 6 / 5 | 0 with key | 0 with key |
| container `/proc/*/{environ,cmdline}` (as root) | clean | clean |
| key file as read by the sandbox user | token only | **the key** (inherent to (b)) |
| container workspace + /tmp live; workspace + .home after; run logs | clean | clean |
| teardown: shm / containers / networks of the run | 0/0/0 | 0/0/0 |
After all runs (22 workspaces, 29 run dirs, both tools dirs, the folder, `E`): OpenAI and DeepSeek keys 0 hits;
base image `docker save hi-base:80d60e8c2bde` 0 hits; **no `auth.json`, no shell_snapshots files**; no gateway
token (`sk-hi-…`) in any workspace either, incl. codex's TRACE log db `logs_2.sqlite`.
**Where codex puts what it is given:** `account/login/start` + `cli_auth_credentials_store="ephemeral"` keeps
it in app-server memory only; it travels adapter → app-server on a stdin pipe. Not in any env, argv or file.
Note: on this machine the host's own shells, dockerd and containerd carry provider keys in their environ
(session environment, not ours); the docker client hirun starts does not (allowlist env).

## Gateway vs file
Same folder, same code: identical results for one-shot, resume, steer, stop/continue on both providers.
Timings within noise (one-shot 6.3 vs 5.4 s, steer 28 vs 34 s: model variance). Gateway wins on secrecy (the
model's shell can read only a token) and needs no CA bundle for model calls. Codex accepts an `http://` base URL
and streams SSE through it fine. One gateway issue (foundation's `door.py`): DeepSeek steer run logged
`gateway error SSLError` once after a 200 (upstream closing TLS without close_notify after the body); codex logged
no retry and the run passed, but the gateway's handler then tries to write a `502` into an already-started
response — once headers are relayed it should just close.

## Contract friction
1. **Provider URL path is unpinned.** Codex appends `/responses` to the base, so it needs `…/v1`. The foundation
   README's OpenAI example (`--provider-url https://api.openai.com`) would 404. Pin it: for `openai-*` shapes
   `HI_PROVIDER_URL` is the SDK base URL including the version path (`https://api.openai.com/v1`,
   `https://api.deepseek.com/v1`); for `anthropic-messages` without `/v1`. The adapter does not guess.
2. **Stale `files` across responses.** `files` writes a template only when non-empty, and `.home` persists, so
   response 2 with no instructions keeps response 1's `.home/.codex/AGENTS.md`. Proposal: an empty render
   deletes the file (or `home/` + `files` targets are reset each response).
3. **No JSON-RPC helper in hi_adapter.** The loop forbids blocking in `on_line`, so the adapter carries its own
   id→callback plumbing (~15 lines: `send`, `call`, reply dispatch, server-request answers). Every P2/P3
   (app-server, ACP) adapter will write the same; candidate for hi_adapter (not forked; reported here).
4. Needed the key's **value** (`provider_key()`): codex's only no-env/no-disk path is the RPC login. Fine.
5. Given but unused: `HI_RESUME`/`HI_MODEL` (line 1 has them), `metadata`, `HTTPS_PROXY` in gateway mode
   (codex honours it in file mode: door `allow api.openai.com:443`), `HI_TOOLS` (PATH is enough).
6. `hi_adapter.py`: no change. Local runs wrote `__pycache__/` into the folder (python imports hi_adapter);
   run.sh sets `PYTHONDONTWRITEBYTECODE=1` — the template's run.sh should too.
7. Workspaces under `/tmp` make codex warn "Refusing to create helper binaries under temporary dir" (PATH
   aliases skipped; nothing failed). The real server's workspace root should not be under /tmp.

## Open issues
- gpt-5-mini and deepseek-chat have no bundled model metadata (warning each run; the survey saw gpt-5-mini
  fumble namespaced MCP tools). `model_catalog_json` could supply it — untested.
- A steer that arrives after `turn/completed` was processed is not delivered (the adapter has finished);
  `steers` < `steers_sent` lets the server see it and re-send it as a `continued` response.
- `.home/.codex` grows ~4–5 MB per conversation (sqlite dbs incl. TRACE logs, rollouts); no pruning.
- Hooks (need `--dangerously-bypass-hook-trust`), MCP, skills: not exercised here (survey covered under exec).
- First docker one-shot took 13–14 s (cold), later ones 5–6 s.
