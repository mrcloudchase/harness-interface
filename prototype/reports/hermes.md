# Stage 2 report: hermes (Hermes Agent 0.19.0, NousResearch)

Paths: `H` = `R/harnesses/hermes/`, `F` = `R/foundation/`, `E` = `R/work-hermes/` (all evidence lives here: run JSONs, `final/`
suite, drivers). All work done 2026-10-20 between 06:28 and 06:57 UTC.

## Verdict
**Works. Tier: `steered`**, both locally and in the docker sandbox, with both `--secret gateway` and `--secret file`.
On the final folder, everything passes in all three modes (local, docker+gateway, docker+file): one-shot with
instructions, ORCHID resume, steer after 3 numbers (count stops at 3, done.txt = DONE), and SIGINT stop through tini
then continue (count stays at 3; the resumed run names the counting and the number).
**Provider:** the Anthropic key ran out of credit at ~06:36. The local Sonnet one-shot, the ORCHID resume and the
stale-URL demo ran on **Anthropic `claude-sonnet-4-6`** before the cutoff. Everything else ran on **DeepSeek
`deepseek-chat` via `https://api.deepseek.com/anthropic`** (anthropic-messages shape). That includes the whole final
suite, all docker proofs and the secret audit, so item 3 (provider swap through the gateway) is proven many times over.
`hermes-agent` 0.19.0 (uploaded 2026-07-20) is still the latest on PyPI.

## The folder (`H`, 257 lines excluding hi_adapter.py)
| file | what it does |
|---|---|
| `harness.json` | provider `https://api.anthropic.com` / `anthropic-messages`; apis `[anthropic-messages]`; install egress `pypi.org`, `files.pythonhosted.org`; files `{".home/.hermes/SOUL.md": "{instructions}"}`; run `steered`, ndjson, timeout 1800 s, stop_timeout 20 s |
| `install.sh` | `uv tool install --exclude-newer 2026-10-19 'hermes-agent[anthropic,acp]==0.19.0'`, with `UV_TOOL_DIR=$HI_TOOLS/uv`, `UV_TOOL_BIN_DIR=$HI_TOOLS/bin`, `UV_PYTHON_INSTALL_DIR=$HI_TOOLS/python` and `UV_COMPILE_BYTECODE=1` (the tools dir is read-only at run time). The venv uses the base image's python3.12 (`bin/python -> /usr/local/bin/python`); the base image id is in the hash. It then checks `hermes --version` and `import acp, anthropic` |
| `run.sh` | sets `HERMES_HOME=$HOME/.hermes`, `TIRITH_ENABLED=0`, `HERMES_YOLO_MODE=1`, `HERMES_ACCEPT_HOOKS=1`, `HERMES_INFERENCE_PROVIDER=anthropic` and `ANTHROPIC_BASE_URL` (from `HI_PROVIDER_URL`, minus `/v1`); unsets `ANTHROPIC_TOKEN`/`CLAUDE_CODE_OAUTH_TOKEN`; sets `PYTHONDONTWRITEBYTECODE=1`; execs the adapter |
| `adapter.py` (203) | pattern P3. Spawns `hermes acp --accept-hooks` (own session) with `ANTHROPIC_API_KEY` = the key file's content, in hermes's environment only. Sends initialize, then session/new or session/load (replayed updates are dropped and summarised as `hi.replayed`), then the main session/prompt. A steer is `session/prompt "/steer "+text` and counts on hermes's ack. A steer acked after the model's last call is re-sent as the next prompt. Stop = `session/cancel`; −32603 or `cancelled` both mean stopped. `session/request_permission` gets `allow_once`. Answer = agent text after the last tool call, minus hermes's steer/queue notices. usage and cost come from diffs of `state.db` `sessions` counters (cost `null` when hermes's `cost_status` is unknown). `repoint()` is explained under friction 1 |
| `hi_adapter.py` | byte-identical copy (`hirun check`: `hi_adapter_identical: true`; foundation tests: 7 OK) |
| `home/.hermes/config.yaml` | `model: {provider: anthropic, base_url: ${ANTHROPIC_BASE_URL}, default: ${HI_MODEL}, context_length: 128000}`, `security.tirith_enabled: false`, memory/skill nudges 0, and a `pre_tool_call` hook that blocks `delegate_task` (hermes expands the `${VAR}`s) |

## Evidence
| proof | mode / provider | result |
|---|---|---|
| install (docker) | install container, egress pypi + pythonhosted | miss **12.9 s**, then hit **0.2 s**; 205 MB; door: 53 allows, 0 denies. Local install 5.6 s |
| one-shot + instructions | local, Sonnet (before cutoff) | `ok`, "4\n\nBANANA" (SOUL.md followed), 7.0 s, 12,208 input tokens (system prompt + tools), $0.0459 |
| ORCHID resume | local, Sonnet (before cutoff) | run 1 "OK." / run 2 "The word you asked me to remember is **ORCHID**.", same resume id |
| resume without `repoint()` | local gateway, Sonnet | `fail` after 25 s: "API call failed after 3 retries", sent to the previous run's dead gateway port (stderr `base_url=http://127.0.0.1:38695`) |
| steer (first try) | local, DeepSeek | **hermes delegated the count to a background subagent and ended the turn** ("I'll let you know when it finishes"). Count stopped at 1 when the run ended. Fixed with the delegate_task block hook; verified: the tool returned the hook's error and the model wrote the file itself |
| **final suite** `E/prove.sh` | local / docker+gateway / docker+file, DeepSeek | all `ok`/`stopped`; see the next table |

| final suite (`E/final/*.json`) | local (gw) | docker gateway | docker file |
|---|---|---|---|
| one-shot ("4\n\nBANANA") | ok 9.4 s | ok 10.4 s | ok 10.5 s |
| ORCHID run 2 | "…**ORCHID**." 8.8 s | "ORCHID." 10.9 s | "ORCHID." 8.9 s |
| steer: sent at count=3 → done.txt at / exit at / final count / steers | 16.1→18.7/22.3 s, 3, 1/1 | 14.3→17.1/19.7 s, 3, 1/1 | 14.6→16.1/20.1 s, 3, 1/1 |
| stop: SIGINT at count=3 → exit, status, count 3 s later | 1.13 s, stopped, 3 | 1.48 s, stopped, 3 | 1.82 s, stopped, 3 |
| continue answer | "completed 1 and 2 … third interrupted (130)" | "Progress: 2 of 30 done … 3 was interrupted" | "completed 3 of the 30 commands" |

Events per steer run (ACP pass-through): `result`×4, `tool_call`×4–5, `tool_call_update`×4, `agent_message_chunk`×60–70,
`usage_update`×3, `available_commands_update`×1. In stop runs the main prompt answered `-32603 'NoneType'… startswith` (local,
gw) or `stopReason: "cancelled"` (file): hermes's bug is racy, and the adapter handles both. An earlier docker+file steer counted
to **8** before DONE: the model had batched several `echo N; sleep 1` calls in one response, and the steer lands only at the next
model call. That is still a pass, but steer latency depends on how many tool calls the model batches.
Docker overhead is ~1–2 s per response. hermes takes ~3 s to `session/new`, which needed `context_length`: without it, it was 9 s.

## Gateway vs file
| | gateway | file |
|---|---|---|
| all proofs | pass | pass |
| resume | needs `repoint()`: the gateway URL is new each session | the URL is stable, so repoint is a no-op |
| key in docker inspect run/door, host `ps`, host environ (hirun tree) | no / no / no / no | no / no / no / no |
| key inside the sandbox | nowhere (hermes holds the token as `ANTHROPIC_API_KEY`) | **hermes's environ** (`ANTHROPIC_API_KEY`), and **readable by the model's shell** via `HI_PROVIDER_KEY_FILE` (checked by `docker exec -u 1000`) |
| shell tool children (bash/eval/sleep) | no `ANTHROPIC_API_KEY` in their environ (hermes strips provider keys from subprocesses) | same |
| egress seen at the door | models.dev **deny**; ~16 GETs to the gateway (`/api/tags`, `/v1/props`, `/version`, `/v1/models`…: hermes's local-server sniffing); 5 of them without credentials (gateway: "refuse … no session token"), the rest 404 upstream | models.dev **deny**; 5–6 CONNECTs to api.deepseek.com (the same probes, hidden inside TLS) |

Audit (`E/audit_live.py`, `E/audit-live-*.json`, run during a live count): no key (DeepSeek, Anthropic or OpenAI) in the tools dirs,
`H`, any workspace + `.home`, run logs (`F/work`) or `E` (0 files). No `hi-*` containers, networks or `/dev/shm` left by my runs.
No image was built for hermes: tools are a bind mount. **Where hermes puts the credential:** `.home/.hermes/auth.json`
gets a `credential_pool.anthropic` entry with `source: env:ANTHROPIC_API_KEY`, `secret_fingerprint: sha256:<16 hex>` and
`base_url`. Nothing in clear text; the gateway token was not found on disk either.
Note: this machine's shell exports `DEEPSEEK_API_KEY`, which my first audit leaked into hirun through a denylist env.
hirun's allowlist is right; audit scripts need the same allowlist.

## What hermes tries to reach at run time, and whether blocking hurts
- **pypi.org** (update check): never seen at run time in ACP. `hermes --version` does it at install time, where pypi is allowed.
- **github.com** (tirith, 38 MB): off with `TIRITH_ENABLED=0` plus `security.tirith_enabled: false`.
- **models.dev**: denied every run, fails at once (403 on CONNECT). Harmless: Sonnet pricing comes from hermes's built-in
  snapshot (`cost_source: official_docs_snapshot`), and context length is fixed in the config.
- **openrouter.ai** (model metadata): gone once `context_length` was set.
- **api.anthropic.com/v1/models** (the ACP model picker): it used `ANTHROPIC_API_KEY` and ignored `ANTHROPIC_BASE_URL`, so in
  file mode with DeepSeek **it would have sent the DeepSeek key to Anthropic**; the door's deny was all that stopped it. Fixed
  with `model.base_url: ${ANTHROPIC_BASE_URL}`: the call now goes to the provider.
- **the provider URL itself**: hermes calls Ollama/LM Studio/llama.cpp endpoints on any unknown base URL. The calls are
  harmless but wasted: ~0.1–0.2 s each through the gateway.

## Contract friction
1. **`HI_PROVIDER_URL` changes per session under the gateway, but hermes stores the base URL per session.** `session/load`
   restores `model_config.base_url` from `state.db`, which beats the environment. Resume then calls a dead door: proven, 25 s
   then fail. Workaround in the adapter: before the load, `UPDATE sessions SET model_config=json_remove(…'$.base_url'),
   billing_base_url=NULL, model=<request model>`. That is a write into the CLI's private DB, fragile across hermes versions.
   **Suggest:** make the gateway URL stable across a session's responses (e.g. a fixed alias such as
   `http://hi-provider:8080`), or document that it is per response. Any CLI that persists its endpoint will hit this.
2. **No model context size in the contract.** hermes probes or guesses it (6 s per start, and calls to openrouter.ai and the
   provider). I fixed it at 128000, which is safe for deepseek-chat (128K), Sonnet and gpt-5-mini. A `context_tokens` field per
   model or provider would let folders stop guessing.
3. **Instructions:** I wrote them to `.home/.hermes/SOUL.md` rather than `AGENTS.md`, so the workspace diff stays the user's and a
   repo's own AGENTS.md is not overwritten (hermes loads only one of `.hermes.md`/AGENTS.md/CLAUDE.md). Gap: `files` skips empty
   results, so a stale SOUL.md (or AGENTS.md) from an earlier response stays when a later one has no instructions.
4. **Given but unused:** `HI_RESUME` (line 1 carries it), `HI_PROVIDER_API` (one shape), `metadata`, `HI_TOOLS` (only via PATH).
   Used: the rest. Not needed: anything else.
5. **hi_adapter.py: unchanged.** Template suggestion: set `PYTHONDONTWRITEBYTECODE=1` in run.sh (local runs wrote
   `__pycache__` into the folder). hermes INFO logs go to stderr through `spawn(stderr=None)`, which is fine.
6. **hirun `--steer-after-lines` / `--stop-after-lines` can't express "after 3 numbers"** (ACP chunk counts vary). I subclassed
   `hirun.Run` in `E/drive.py` to trigger on `count.txt` lines. The real server won't need this; the prototype's tests would.
7. **API shapes:** `openai-chat` also works. A scratch variant (`E/openai-chat-try-*`: `provider: custom`,
   `base_url: ${HI_PROVIDER_URL}/v1`, `api_key: ${HI_KEY_VALUE}`, `api_mode: chat_completions`) answered "4" with `gpt-5-mini`
   through the local gateway, and left no key on disk. I did not ship it: it needs run.sh to pick a config per
   `HI_PROVIDER_API`, and all proofs would need re-running. hermes sends `OPENAI_API_KEY` only to `*.openai.com` hosts, so
   the gateway URL needs `api_key` in config.

## Open issues
- hermes 0.19.0 bugs and behaviours handled in the folder: `session/cancel` → −32603 (racy); SIGINT ignored by `hermes acp`
  (never sent: own session); `delegate_task` is always background, and ACP ignores `agent.disabled_toolsets` (blocked by a shell
  hook); `session/set_model` guesses providers and fetches the OpenRouter catalog (not used: model via `${HI_MODEL}`).
- A steer that lands while the model writes its final answer stays as hermes's `_pending_steer`. The adapter re-sends it as a
  new prompt, so hermes may also inject it into a later tool result (duplicate text). Not observed; it comes from reading the source.
- `cost_usd` is `null` for DeepSeek (hermes has no price for it under provider anthropic). The usage counters exclude cache
  reads from `input_tokens` (`cache_read_tokens` is separate). hermes's ~10–12K-token system prompt is paid on every call.
- Sonnet steer/stop were not re-run after the cutoff. The steered mechanics don't depend on the provider, and the survey
  passed both on Sonnet.
- Background title generation (`maybe_auto_title`) can make an auxiliary model call after `end_turn`. It is cut short when
  we close stdin, and no extra POST was seen at the door.
- Size: tools dir 205 MB; `.home/.hermes` gains a 5.8 MB `models_dev_cache.json` only when models.dev is reachable (local).
