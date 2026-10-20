# Stage 2 report: pi

`H` = `R/harnesses/pi/`, `F` = `R/foundation/`, `P` = `R/../pi-work/` (my test drivers and workspaces). All runs on 2026-10-20.
Pinned `@earendil-works/pi-coding-agent@1.3.0`, still the latest on npm (published 2026-10-15; `npm view … versions`).

## Verdict
**Works, tier `steered`, local and in the docker sandbox, under both `--secret gateway` and `--secret file`.**
One-shot, resume, steer and SIGINT stop + continue all pass in docker on both secret modes. All three API
shapes work: anthropic-messages, openai-chat and openai-responses. The folder needed no change to the
contract or to `hi_adapter.py`.
**Provider note:** the Anthropic key ran out of credit at about 06:36 UTC. Only the first local one-shot,
the local ORCHID resume and one local steer attempt ran on `claude-sonnet-4-6`. Everything after that ran on
DeepSeek `deepseek-chat`, plus one OpenAI `gpt-5-mini` run per shape. The credit error itself was a useful
test: the adapter returned `status: fail` with the 400 message as the answer, while the exit code was 0.

## The folder
| file | what it does |
|---|---|
| `harness.json` | default provider anthropic. `apis`: all three. `install.egress`: `registry.npmjs.org`. `files`: `{".home/.pi/agent/AGENTS.md": "{instructions}"}` (pi's global context file, so a repo's own AGENTS.md is never overwritten; pi loads both). `run`: steered, ndjson, 900 s, stop 15 s |
| `install.sh` | `npm i -g --prefix $HI_TOOLS @earendil-works/pi-coding-agent@1.3.0`, then `pi --version`. 154 MB, 118 packages |
| `run.sh` | `PI_OFFLINE=1 PI_TELEMETRY=0 PI_SKIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1`, then exec adapter.py (7 lines) |
| `adapter.py` | 166 lines. See below |
| `hi_adapter.py` | byte-identical copy (`hirun.py check`: identical). Foundation unit tests: 7/7 OK |
| `home/` | none needed (removed) |

adapter.py:
- **Provider.** pi has no base-URL env var and does not expand `$VAR` in `baseUrl`, so every response merges `$HOME/.pi/agent/models.json` (keeping anything `home/` put there).
  - `baseUrl`: HI_PROVIDER_URL with any trailing `/v1` removed for anthropic. For openai shapes, `/v1` is appended only when the URL is a bare host.
  - `apiKey`: `"!cat '<HI_PROVIDER_KEY_FILE>'"`. pi runs that command for each request, so the key or token never enters pi's env or argv, and models.json holds only the path.
  - Model choice: the built-in provider (`anthropic`, or `openai` for responses) is used if `pi --offline --list-models <model>` lists the model under it (~0.3 s), which gives catalog limits and prices. Otherwise (deepseek-chat, or any model on openai-chat) it uses a custom provider `hi` with the pi api name (`openai-chat` → `openai-completions`) and `cost_usd: null`. The survey found that pi bills an unknown id under a built-in provider at a fallback price, so the adapter never relies on that.
- **Session.** The id is chosen up front (uuid4, or HI_RESUME) and written to HI_OUTPUT before pi starts. A new session gets `--session-id <id>`. A resume finds `sessions/*/*_<id>.jsonl` and passes `--session <file>`, which works from any cwd. `get_state` confirms the id.
- **Driving pi.** `pi --mode rpc --provider P --model M` runs in its own session, and every pi record passes through to stdout unchanged. The adapter sends `get_state`, then `prompt`.
  - Steer: `prompt` with `streamingBehavior:"steer"`. The 1.3.0 docs also list `{"type":"steer"}`; I kept `prompt` because it also starts a run when pi is idle. The steer counts as accepted on `disposition` `queued` or `started`.
  - Stop: `clear_queue`, then `abort`.
  - Done: `agent_settled` with no steer response outstanding and an empty `queue_update`.
  - Status: `stopped` if settled `aborted` or we asked for a stop; `fail` if the last assistant `stopReason` is `error`; otherwise `ok`.
  - usage: the sum over this response's assistant messages, reported as `input/output/cache_read/cache_write_tokens`.

## Evidence (A = Anthropic claude-sonnet-4-6, before the cutoff; D = DeepSeek deepseek-chat; O = OpenAI gpt-5-mini)
| # | where | test | result |
|---|---|---|---|
| 1 | local, gw, A | one-shot "17*23", instructions "end with PINEAPPLE" | ok `391\n\nPINEAPPLE`, $0.0091, 2.97 s |
| 2 | local, gw, A | ORCHID: run 1, then resume by id | `OK.` → `The word you asked me to remember is **ORCHID**.` (same resume id, 2.1 s and 2.0 s) |
| 3 | local, gw, A | steer at count 3 | Inconclusive. Sonnet chained all 30 numbers in one bash call, so the steer queued at 37.6 s and ran after it (done.txt=DONE, count 30). The retry hit the **credit error** → `fail` + 400 text, exit 0 |
| 4 | local, gw, D | steer (anthropic shape) | Pass. Queued while a parallel batch of 5 bash calls ran, injected after the batch: count **5**, done.txt=DONE, ok, 6.3 s |
| 5 | local, gw, D | stop at count 3 (killpg SIGINT), then continue | stopped in **0.06 s**, count stayed 3. Resumed: "the file actually contains **1, 2, and 3** … 3 of 30 numbers written" |
| 6 | local, gw | shapes | D openai-chat (`…/v1` and the bare host), O openai-responses ($0.0010, catalog-priced), O openai-chat: all ok `391 PINEAPPLE` |
| 7 | docker | install | miss **15.1 s**, then hit **0.14 s**. The door allowed only registry.npmjs.org (15 CONNECTs, 0 denied) |
| 8 | docker, gw / file, D | one-shot + instructions | ok `391\nPINEAPPLE`, 5.05 s / 4.81 s |
| 9 | docker, gw / file, D | ORCHID resume (anthropic shape) | `OK` → `ORCHID` in both modes (3.4–5.1 s per response) |
| 10 | docker, gw / file, D | ORCHID resume (openai-chat shape) | `OK` → `ORCHID` in both modes |
| 11 | docker, gw / file, D | steer at count 3 | Second attempt in each mode: count **3**, done.txt=DONE, steers 1/1, 11.2 s / 12.6 s. First attempts: gw cue landed at 10 (DeepSeek ran parallel batches of 10) and stopped at **20**. file: DeepSeek wrote all 30 in one bash call |
| 12 | docker, gw, D openai-chat | steer | count **7**, done.txt=DONE, ok, 8.4 s |
| 13 | docker, gw / file, D | SIGINT via `docker kill -s INT` → tini → adapter → clear_queue+abort | stopped, exit 0, **0.21–0.24 s**, count stayed 3, session saved |
| 14 | docker, gw / file, D | continue after stop | gw: "numbers **1** and **2** were written … **3** was issued but got aborted". file: "`count.txt` currently contains 1, 2, 3 … Remaining: 4 through 30" |
| 15 | docker, gw, O | openai-responses | ok `391`, $0.00062, gateway `POST /v1/responses` |
| 16 | docker, gw, D | user's AGENTS.md + instructions | Both files reached pi's `project_context`. The user's AGENTS.md was untouched and files_changed was empty |

Event types seen: `response` (get_state, prompt, abort, clear_queue), agent_start, turn_start/turn_end, message_start/update/end,
tool_execution_start/update/end, queue_update, agent_end, agent_settled{aborted}. A pi steer lands only after the
**whole current tool batch** finishes, before the next model call. If the next model call is already in flight, it lands one batch later
(row 11). With models that batch or chain bash calls, steer latency equals the batch length. That is pi's design, not a folder bug.

## Egress (provider only)
- With PI_OFFLINE=1, the door log shows only the provider: gateway lines `POST /anthropic/v1/messages`, `/v1/chat/completions` or `/v1/responses`, or file mode `allow api.deepseek.com:443` (a single CONNECT; pi keeps the connection alive).
- Without PI_OFFLINE (a copy of the folder with the export removed): **3 × `door deny pi.dev:443`** per response (catalog, version, telemetry). The run was unaffected (ok, 3.5 s against ~3.4–3.9 s), so blocking them does no harm and PI_OFFLINE simply keeps them quiet.
- Gateway: one `gateway error IncompleteReadError` sometimes appears at the end of a run. It is pi's idle keep-alive socket closing, and the answer is unaffected.

## Gateway vs file
Both work with no difference in the folder: the adapter's `!cat <file>` reads whatever the file holds.
- With the gateway, pi gets `HI_PROVIDER_URL=http://hi-door-<sid>:8080[/anthropic]` and an `sk-ant-api03-hi-…` token. pi sends plain HTTP to the door (NO_PROXY includes the door) and needs no CA.
- With file mode, pi uses the CONNECT door to api.deepseek.com, with the CA from `NODE_EXTRA_CA_CERTS`.
- The gateway is preferable here for the usual reason: in file mode, pi's bash tool (and so the model) can `cat` the real key.

## Secret audit (`P/audit.sh gateway|file`, during a counting run and after teardown; prints names only)
| where | gateway: key / token | file: key |
|---|---|---|
| `docker inspect` run, door | clean / clean | clean |
| host `/proc/*/cmdline` (ps) | clean / clean | clean |
| environ of hirun's `docker run` client and `docker-init` | clean / clean | clean |
| every process in the container (adapter, pi, bash) | clean / clean | clean |
| host environ under any name **other than the machine's own `DEEPSEEK_API_KEY`** | clean / clean | clean |
| workspace + `.home`, run logs (stdout/stderr/output/result), tools dir + install log | clean / clean | clean |
| `/dev/shm/hi-<sid>`, containers after teardown | gone | gone |
| base image `docker image inspect` + `history` (DeepSeek, OpenAI keys) | clean | clean |
- Final sweep with all three keys over `P`, `F/work/runs`, the tools dirs and `H`: clean.
- **Where pi puts what it is given:** `.home/.pi/agent/models.json` holds `"apiKey": "!cat /dev/shm/hi-<sid>/key"` (a path only). `auth.json` is `{}`. pi persists no key or token; the token exists only in pi's memory and in the `cat` child's stdout for each request.
- Machine finding: this host exports **`DEEPSEEK_API_KEY`** to every shell, dockerd and containerd, in addition to the `EXT_ANTHROPIC_API_KEY` the foundation found. hirun's allowlisted child env kept it out of every docker client and harness process.

## Contract friction
- **Needed but not given:** a pinned meaning for `HI_PROVIDER_URL`. The foundation passes `https://api.openai.com` (bare host) for OpenAI, while the brief and DeepSeek use `https://api.deepseek.com/v1`. pi wants anthropic bases **without** `/v1` and openai bases **with** it, so the adapter guesses (strip, or append on a bare host only). Proposal: HI_PROVIDER_URL = the base URL the shape's official SDK takes (Anthropic without `/v1`, OpenAI with `/v1`). A harness should never have to edit it.
- **Given but unused:**
  - `HI_TOOLS`, because PATH is enough.
  - `HI_MODEL` and `HI_RESUME` env, because the adapter reads line 1 (they duplicate it).
  - `metadata`.
  - `hi_adapter.provider_key()`, because pi reads the file itself.
  - `home/`.
  - The `{instructions}` default target `AGENTS.md` in the workspace: I moved it to `.home/.pi/agent/AGENTS.md` so it cannot overwrite or pollute the user's repo. Recommend this pattern for every harness that has a global instructions file.
- **`files` with empty content are "not written"**, so a stale `.home/.pi/agent/AGENTS.md` from an earlier response with instructions survives into a later response without any. Propose: empty content means delete.
- **hi_adapter.py: unchanged.** The adapter reads `self.stopping_since` (a loop attribute) to tell a stop-abort from a real error. Consider making `stopping` a documented property.
- **hirun (test tooling, not contract):**
  - `--steer-after-lines` cannot target "after 3 numbers" for a CLI that streams deltas, or one whose long tool calls print nothing. `P/drive.py` wraps `hirun.main` and polls `count.txt` from a thread. A real server steers on user input, so this is test-only.
  - In local mode, Python wrote `__pycache__` into the (otherwise ro) folder, so run.sh sets `PYTHONDONTWRITEBYTECODE=1`. The template run.sh should do the same.

## Open issues
- The idle-steer path is untested end to end (a steer arriving after `agent_settled` → `disposition:"started"` → wait for the next settle), because the adapter exits at settle and hirun sends nothing later. The code path exists.
- Cost is `null` for any model outside pi's catalog under the anthropic or openai provider, and for everything on openai-chat. Pricing for DeepSeek would need a per-model `cost` in models.json, which the contract gives no source for.
- `--list-models` adds ~0.3 s per response. It could be cached per (tools dir, model).
- Steer granularity depends on the model's tool batching (rows 3, 11), not on pi or the folder. Parallel tool calls cannot be turned off from the folder.
- Anthropic shape on real Anthropic in docker is unproven because of the credit cutoff. The same code path passed with DeepSeek's anthropic endpoint through the gateway (x-api-key swap), and locally with Anthropic before the cutoff.

Reproduce: `python3 F/hirun.py run H --task … --model deepseek-chat --provider-url https://api.deepseek.com/anthropic
--provider-api anthropic-messages --key-file $S/DEEPSEEK_API_KEY [--secret file]`. Drivers: `P/steer.sh`, `P/stopcont.sh`, `P/orchid.sh` and `P/audit.sh`
(each takes a name, then hirun args), `P/drive.py`, and `P/tl.py <rundir>` (event timeline). Result JSONs are `P/*.json`.
