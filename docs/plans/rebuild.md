# Plan: rebuild harness-interface (2.0.0)

**Status: a plan, not built.** Agreed with the owner on 2026-10-20, on branch `v2`. Written so that whoever builds it,
person or agent, can do so from this file and `prototype/` alone, with no memory of the conversations it came from.
Where something is a decision it is marked **Decided**; don't reopen it without the owner. Where it still has to be
proven it is marked **Prove**.

It replaces the earlier `docs/plans/sessions-and-interrupt.md` (branch `plan/mid-turn-steering`), whose sessions API it
keeps, and everything that plan said about the old contract and image.

Contents: 1 what and why · 2 decisions · 3 the evidence · 4 the contract · 5 the harness folder · 6 install and sandbox ·
7 secrets · 8 the API · 9 the code · 10 build order · 11 tests · 12 harness folders · 13 what is removed · 14 rules that
must always hold · 15 open issues · 16 risks.

---

## 1. What we are building, and why

harness-interface is an **execution layer for coding harnesses** (Claude Code, Codex, pi, OpenCode, Hermes, and any
harness someone writes later). A client asks for work; the server runs the named harness in a locked-down container,
streams what it prints, and keeps a record of what it did. People reach it through the OpenAI Responses wire format over
HTTP, through Python directly, and through frontends built on the API later.

The rebuild exists for four reasons:
- **Interactive sessions.** A client should be able to drive any harness the way a person drives an interactive CLI:
  start work, check on it, put more text into the work in progress, stop it, and continue it later with the harness's
  memory intact. It degrades per harness (`steered` → `continued` → `responded`), so every harness works and the best
  ones feel live. No other harness platform does this across many harnesses.
- **A lightweight, secure sandbox.** The old default image baked every CLI into ~10 GB. Now a minimal base image holds no
  CLIs and no secrets; each harness is installed once per version into a cached tools directory and mounted read-only
  into its sessions. A session can reach only its model provider, and with the provider gateway it never even holds the
  real key.
- **A minimal contract that fits any harness, now or later.** The contract is a terminal session: a program, a
  directory, files, an environment, input, output and signals. Everything CLI-specific lives in the harness's folder.
- **Less code doing more.** KISS, DRY, SRP, objects only where there is state, negative-space programming, and
  test-driven development, layer by layer.

---

## 2. The decisions (all **Decided** with the owner)

1. **Everything is a session.** A session is one harness, its workspace, the CLI's own conversation (`resume`), and every
   response in it. "Run", "turn" and "conversation" leave the API, the code and the docs. A **response** is one request's
   result in the OpenAI Responses shape.
2. **Rebuild in place on branch `v2`**, merged to `main` as 2.0.0 when done. **No backward compatibility**: there are no
   users yet. No 1.x data migration, no old routes, no old field names.
3. **Keeper and `hi` are dropped** from this repository for the rebuild. The server runs from its own entry point
   (`harness-interface`). A new CLI that feels like a harness CLI is built later, as a client of the API.
4. **Cached install per harness version.** A minimal base image holds no CLIs and no secrets. A harness's `install.sh`
   runs once in an install container (egress only to its declared install hosts, no secrets), filling a tools directory
   cached by a hash of `install.sh`, the base image and the CPU architecture. Sessions mount it read-only.
5. **A provider can be chosen per request**, and every provider has an API shape: `anthropic-messages`,
   `openai-responses` or `openai-chat`. A harness declares the shapes it speaks; a request for a shape it can't speak is a
   400 before anything runs.
6. **`home/` replaces the old `artifacts` file**: a folder tree copied into `$HOME` before every response.
7. **Secrets go through a provider gateway in the egress door.** The real key reaches only the door; the harness gets a
   per-session token and a door URL. A read-only key file is the fallback for a CLI that can't use the gateway. The key's
   value is **never** passed as an environment variable.
8. **The contract cuts and definitions in §4** (cut the duplicate and unused inputs; pin the provider URL, stale `files`,
   `steers` and `usage`).
9. **Cost is the harness's advisory figure for now.** No server-side price table yet (maybe later).
10. **Shared adapter code is `hi_adapter.py`, copied byte-identical into every folder** and checked, not a library the
    server injects.
11. **First wave: Claude Code, Codex, pi, OpenCode, Hermes.** They span five adapter patterns, which is how we find the
    most flexible minimal contract. The other 18 surveyed harnesses follow, one at a time.
12. **The contract carries a version** (`"contract": 1` in `harness.json`), and **a harness may bring its own image**
    (a Dockerfile built `FROM` the base) when it needs operating-system packages its `install.sh` can't add.
13. No hard size budget: the code must be as tight as it can be while doing what is needed.

---

## 3. The evidence (read before changing anything)

Everything below was proven before this plan was written. The material is committed under `prototype/`:

| Path | What it is |
|---|---|
| `prototype/survey/SUMMARY.md` and `prototype/survey/<name>.md` | all 23 harnesses installed and driven directly: inputs, provider wiring, artifacts, outputs, state, resume, steering, graceful stop. All 23 can be steered (19 natively, 3 by cancel-and-reprompt, 1 after a patch to its own code); none had to be dropped |
| `prototype/foundation/` | the template folder (`template/`, with a stand-in CLI that needs no model), the minimal base image (`base.Dockerfile`), the egress door with the gateway (`door.py`), the prototype runner that implements the candidate contract (`hirun.py`), and its proofs (`prove.py`, 19 of 19 pass; `tests/`) |
| `prototype/harnesses/<name>/` | the five first-wave folders rebuilt from the template; `claude-code/proof/` keeps one full evidence set |
| `prototype/reports/` | each agent's report: foundation, claude-code, codex, pi, opencode, hermes |
| `prototype/FINDINGS.md` | the consolidated result: the proven contract, template, sandbox, secrets, and the derived server requirements |

What it proved, in one table (details in `prototype/FINDINGS.md` §1):

| | Claude Code | Codex | pi | OpenCode | Hermes |
|---|---|---|---|---|---|
| Pin | 2.1.304 | 0.163.0 | 1.3.0 | 1.19.3 | 0.19.0 |
| Tier reached | steered | steered | steered | steered | steered |
| Install miss → cached hit | 29.5 s → 0.0 s | 11.7 s → 0.16 s | 15.1 s → 0.14 s | 13.8 s → 0.15 s | 12.9 s → 0.2 s |
| Stop → exit, sandboxed | 0.2–0.3 s | 0.3 s | 0.2 s | 0.3–0.6 s | 1.5–1.8 s |
| Steer after 3 numbers | stopped at 4 | 3 | 3 | 3–4 | 3 |
| Shapes proven | anthropic-messages | openai-responses | all three | all three | anthropic-messages |
| Secret modes | gateway + file | gateway + file | gateway + file | gateway + file | gateway + file |

Every one was proven locally and in the hardened sandbox, with a cached read-only install, and every stopped session
resumed knowing what it had been doing. Secret audits found the key in no image, tools directory, workspace, log,
`docker inspect` or host process. `hi_adapter.py` stayed byte-identical in all five.

The Anthropic key ran out of credit partway through (~06:36 UTC on 2026-10-20); the proofs after that ran on DeepSeek's
Anthropic-shaped endpoint or OpenAI. What still needs Anthropic is in §15.

---

## 4. The contract (version 1)

### 4.1 The idea

Whatever a harness is (a CLI, a local server, an RPC tool, an SDK, something not invented yet), it can be run as **a
program, in a directory, with files, an environment, input, output and signals**. The contract assumes only that. Each
harness folder translates its own CLI into it. It lives in one module (§9), and nothing else knows it.

### 4.2 What stays the same, whatever the harness

| What is always true of a harness | The contract element |
|---|---|
| It must be installed | `install.sh` fills `$HI_TOOLS` (binaries in `$HI_TOOLS/bin`); no secrets; declared install hosts only |
| It is started | one command: `bash run.sh`, in the workspace |
| It gets a task | stdin line 1, one compact JSON line: `{"task": "…", "resume": "…"}` |
| It may take more text while it works | each later stdin line is one JSON string |
| It works on files | the workspace, read-write; its changes are diffed |
| It has config and state | `HOME` = `<workspace>/.home`, kept between responses; the folder's `home/` copied in first |
| It calls a model | `HI_PROVIDER_URL`, `HI_PROVIDER_API`, `HI_PROVIDER_KEY_FILE`, and `HI_MODEL` |
| It produces output | stdout and stderr, streamed and kept unchanged |
| It ends with a result | the JSON file at `$HI_OUTPUT` |
| It may remember a conversation | `resume`: an opaque string it reports and gets back on line 1 next time |
| It must be stoppable | SIGINT, or end of stdin, means stop gracefully; a kill follows `run.stop_timeout_s` |
| It says what it can do | `harness.json` |

### 4.3 What the contract never assumes (negative space)

No protocol (JSON-RPC, ACP, HTTP, stream-json and WebSockets live in the folder's adapter). No output format or event
schema (output is bytes). No language, CLI flags or conventions. No particular provider. Not even that it can steer or
resume: the tiers degrade (§4.8). No network beyond its provider, and no secret it can see under the gateway.

### 4.4 `harness.json`

A closed schema: an unknown or missing field is an error.

```json
{
  "contract": 1,
  "name": "claude-code",
  "description": "Claude Code, headless, steered over stream-json.",
  "provider": {"url": "https://api.anthropic.com", "api": "anthropic-messages"},
  "apis": ["anthropic-messages"],
  "install": {"egress": ["registry.npmjs.org"], "timeout_s": 600},
  "files": {".home/.claude/CLAUDE.md": "{instructions}"},
  "run": {"interrupt": "steered", "stdout": "application/x-ndjson", "timeout_s": 1800, "stop_timeout_s": 20,
          "credential": "gateway", "egress": []}
}
```

| Field | Meaning | Evidence |
|---|---|---|
| `contract` | the contract version this folder was written for; the server refuses one it doesn't know | Decided (§2.12) |
| `name` | `[a-z0-9-]+`; names the tools directory | all five |
| `description` | one line | all five |
| `provider` | the default provider: `{url, api}`, `api` ∈ `apis` | all five |
| `apis` | the shapes the harness speaks | pi and OpenCode: 3; the others 1 |
| `install` | `egress` (hosts the install may reach) and `timeout_s` | npm only (3), npm + PyPI (OpenCode), PyPI (Hermes) |
| `files` | `{path: template}`, rendered before every response; `{instructions}` is the request's instructions | all five, each one entry under `.home/` |
| `run.interrupt` | `steered`, `continued` or `responded` | all five `steered`; the other two are the degradation tiers |
| `run.stdout` | content type of stdout | all five `application/x-ndjson` |
| `run.timeout_s`, `run.stop_timeout_s` | the response's limit; the grace between SIGINT and the kill | all five (900–1800 s; 15–20 s) |
| `run.credential` | `gateway` (default) or `file` (§7) | both proven in all five |
| `run.egress` | extra hosts a session may reach beyond its provider; default none | none of the five needed one; kept for harnesses with web tools |

Optional, in the folder rather than the JSON: `image.Dockerfile`, built `FROM` the base image, for operating-system
packages (§6.4).

Cut from the draft because no harness used them: `sandbox` (replaced by `image.Dockerfile` and `run.egress`),
`run.argv` (always `bash run.sh`), `run.env` (`run.sh` holds it), `metadata`.

### 4.5 What a harness is given

| Item | Value |
|---|---|
| working directory | the workspace (`HI_WORKSPACE`), at the same path inside and outside the sandbox |
| `HOME` | `$HI_WORKSPACE/.home` |
| `HI_HARNESS_DIR` | the folder, read-only |
| `HI_OUTPUT` | the result file's path, in a per-response directory **outside** the workspace |
| `HI_PROVIDER_URL` | the provider base URL, by the rule in §4.7, or the gateway's URL for the same path |
| `HI_PROVIDER_API` | the shape |
| `HI_PROVIDER_KEY_FILE` | a read-only file holding the per-session token (gateway) or the key (file mode), at a stable path |
| `HI_MODEL` | the model the request named, or empty |
| `PATH` | `$HI_TOOLS/bin` first |
| `HTTPS_PROXY`, `NO_PROXY` (and lowercase) | the door; `127.0.0.1,localhost,<door>` so local servers inside the run work |
| stdin line 1 | `{"task", "resume"}` as one compact JSON line |
| later stdin lines | one JSON string each (a steer), for `steered` harnesses |
| `$HOME` contents | the folder's `home/` copied in, then `files` rendered |

`HI_TOOLS` is given to `install.sh` only. Cut from the draft: `HI_TASK`, `HI_REQUEST`, the `HI_RESUME` and model
duplicates on stdin, instructions on stdin (they reach the harness only through `files`), `metadata`, the key's value
as an environment variable.

### 4.6 What it gives back

- **stdout and stderr**: streamed as they are written and kept byte for byte. All five first-wave adapters pass the
  CLI's own events through unchanged and add `hi.*` events of their own.
- **workspace changes**: the diff of everything outside `.home/`.
- **`$HI_OUTPUT`**: one JSON object, written **atomically** (tmp, fsync, rename), **early** (as soon as `resume` is
  known, with `"status": "running"`) and again at the end:
  ```json
  {"answer": "…", "status": "ok", "resume": "…", "usage": {"input_tokens": 0, "output_tokens": 0,
   "cache_read_tokens": 0, "cache_write_tokens": 0, "reasoning_tokens": 0}, "cost_usd": null, "steers": 1}
  ```
  `status` ∈ `running | ok | fail | stopped`. Status comes from the CLI's events, never its exit code (the out-of-credit
  runs exited 0 with `fail`). Every key is optional; `usage` keys are the five above (others allowed); `cost_usd` is the
  harness's advisory figure.

### 4.7 Definitions the prototype pinned down

- **Provider URL.** The base URL the shape's **official SDK** takes: `anthropic-messages` without `/v1`
  (`https://api.anthropic.com`, `https://api.deepseek.com/anthropic`); `openai-*` with the version path
  (`https://api.openai.com/v1`, `https://api.deepseek.com/v1`). The server validates it; adapters never guess. Under the
  gateway the same path follows the gateway's base.
- **Stale `files`.** Every response renders every `files` entry; an **empty render deletes** the file. (Without this, a
  response with no instructions kept the previous ones: four of five harnesses hit it.)
- **`steers`.** The number of steer lines the CLI acknowledged, in order. If `steers` is less than the number sent, the
  rest arrived too late (OpenCode proved this happens). When the response ends `ok`, the server sends the rest, joined,
  as a new response that continues the session; when it ends `stopped` or `fail`, it reports them undelivered. The
  server never sends a steer after it has asked for a stop.
- **Early `running`.** If a response is cut off while `HI_OUTPUT` still says `running`, the server records `stopped`
  when it had asked for a stop and a `resume` exists, otherwise `fail`.

### 4.8 Control, and how interrupt degrades

- Stdin stays open for the whole response. **End of stdin** = stop gracefully. **SIGINT** (to the run's process group,
  through `docker run --init` with `TINI_KILL_PROCESS_GROUP=1`) = stop gracefully. The kill follows `stop_timeout_s`.
  `run.timeout_s` triggers the same stop.
- Interrupt, decided by the server per session:
  1. **Idle:** start a new response that continues the session → `continued`.
  2. **Running and `steered`:** write the text as a line → `steered`. If it can't be delivered, fall through.
  3. **Otherwise:** stop the response, then start a new one with the text, resuming the CLI's conversation →
     `continued`, or `responded` if the harness promises nothing more.

### 4.9 The smallest possible harness

`harness.json`; an `install.sh` that installs nothing; a `run.sh` that reads line 1, prints, and writes
`{"answer": "…", "status": "ok"}` to `$HI_OUTPUT`. It is `responded` with no resume, and it works.

---

## 5. The harness folder

```
<name>/
  harness.json     §4.4
  install.sh       installs the pinned CLI into $HI_TOOLS; asserts the version; pins anything else it fetches
  run.sh           cd "$HI_WORKSPACE"; CLI-native env (base URL, quiet switches, PYTHONDONTWRITEBYTECODE=1);
                   exec python3 -u "$HI_HARNESS_DIR/adapter.py"
  adapter.py       drives the CLI: request in, steers in, SIGINT → the CLI's own stop; writes HI_OUTPUT
  hi_adapter.py    the shared plumbing, byte-identical in every folder
  home/            optional; copied into $HOME before every response (settings, skills, MCP config, hooks)
  image.Dockerfile optional; FROM the base image, for OS packages (§6.4)
```

**`hi_adapter.py`** (stdlib, Python ≥ 3.9; 194 lines in the prototype) provides: `Output` (atomic, field- and
status-checked), `read_request` (line 1), `provider_key()`, `child_env()` (loopback never proxied), and `Adapter`: one
event loop over the CLI's lines, stdin steers, end of stdin and SIGINT/SIGTERM; `spawn` (the CLI in its own session, so
only the adapter sees our SIGINT); `emit`; `accepted_steer`; `finish`; stop grace; `_reap` (close stdin, wait, kill the
CLI's process groups); an adapter exception becomes `fail`. It is copied identically into every folder, not injected by
the server, so a folder runs on its own and the contract stays env, stdin and files. Three checks refuse a drifted copy:
a unit test over every folder, the folder loader, and the run itself.

**Additions to make** (asked for by the first wave; change every copy in one commit):
1. a JSON-RPC helper (`send`, `call(method, params, then)`, id → callback dispatch, answering server requests);
2. a public `pump(iterable, name)` for extra event sources (OpenCode's SSE stream);
3. an `on_finish` hook before `_reap` (OpenCode stops its server cleanly);
4. a `stopping` property (every adapter tells a stop from an error with it);
5. `PYTHONDONTWRITEBYTECODE=1` in the template `run.sh`;
6. the template's default `files` target under `.home/`, never the user's own `AGENTS.md`.

**Adapter patterns** of the first wave, and their done and stop conditions (more in `prototype/FINDINGS.md` §3 and
`prototype/survey/SUMMARY.md` §2 for the other 18):

| Harness | Pattern | Done | Stop |
|---|---|---|---|
| Claude Code | stream-json on stdin (`--input-format stream-json --replay-user-messages --session-id`) | a `result` and every sent line echoed back | `control_request` interrupt |
| Codex | `codex app-server` JSON-RPC (`turn/steer`) | `turn/completed`, nothing queued | `turn/interrupt` |
| pi | `pi --mode rpc` (`prompt` with `streamingBehavior: "steer"`) | `agent_settled`, no steer pending | `clear_queue`, then `abort` |
| OpenCode | `opencode serve` on loopback + SSE (`prompt_async`) | session idle, every prompt seen | `POST /session/{id}/abort` |
| Hermes | ACP over stdio (`/steer` prompt) | the main prompt's result | `session/cancel` |

**Instructions** go where each CLI reads its user-level file, under `.home/`, so the user's own files are never touched:
`.home/.claude/CLAUDE.md`, `.home/.codex/AGENTS.md`, `.home/.pi/agent/AGENTS.md`,
`.home/.config/opencode/AGENTS.md`, `.home/.hermes/SOUL.md`.

---

## 6. Install and sandbox

### 6.1 The base image

`prototype/foundation/base.Dockerfile`: Python 3.12 slim, Node 22 and npm, uv, git, CA certificates, user `hi` uid 1000;
no CLIs, no secrets, no fetch at build time; tagged by a hash of the Dockerfile; 405 MB. No tini: `docker run --init`
supplies it. git is 99 MB of that and nothing used it yet; keep it only if git workspaces need it (§15).

### 6.2 The install container

`--init`, the hardening flags (§6.3), uid 1000, its own `--internal` network with a door that allows only
`install.egress`, no DNS, `HOME=/tmp`, the folder read-only, the tools directory read-write **at its final path** (npm and
uv write absolute paths), and **no provider variables or secrets**. Cache key:
`tools/<name>-sha256(install.sh, image.Dockerfile, base image id, CPU architecture)[:12]`. The directory is complete only
when a marker is written last; a failed or timed-out install deletes it; one lock per key. Adding or changing a harness
starts its install in the background; the harness shows `installing`, `ready` or `failed` with the install log.

### 6.3 The session container

```
docker run --rm -i --init -e TINI_KILL_PROCESS_GROUP=1
  --cap-drop ALL --security-opt no-new-privileges --read-only
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=512m --pids-limit 512 --memory 4g --user 1000:1000
  --network hi-net-<session>   -w <workspace>
  -v <workspace>:<workspace>  -v <folder>:<folder>:ro  -v <tools>:<tools>:ro  -v <rundir>:<rundir>
  -v <credential file>:/run/hi/key:ro
  -e NAME ...                  (names only; values come from the docker client's allowlisted environment)
  <image> bash <folder>/run.sh
```

A per-session `--internal` network; the door is its only member also on the bridge. File mode: the door's CONNECT
allowlist is the provider host plus `run.egress`. Gateway mode: the door serves the gateway, plus CONNECT for `run.egress`
only. Proven: no DNS, the host and other addresses unreachable, other hosts refused, loopback servers inside the
container work. The door's refusal log is how hidden runtime downloads are found (OpenCode's ripgrep download broke its
search tools until it moved into `install.sh`; Hermes would have sent a DeepSeek key to `api.anthropic.com` in file mode).

### 6.4 A harness's own image

A folder may carry `image.Dockerfile` (`FROM` the base image) for operating-system packages that `install.sh`, running as
a normal user, cannot add. It is built once, tagged by its content, and runs with the same hardening. The default stays
the minimal base. **Prove** with a stand-in that needs an OS package.

### 6.5 Teardown

`docker rm -f` the run and the door, remove the network, overwrite and unlink the credential file. On startup, sweep
everything named `hi-*` left by a crash.

---

## 7. Secrets

| Where the key was found | env var by name | key file (0400, tmpfs, read-only mount) | **gateway** |
|---|---|---|---|
| `docker inspect` | yes | no | no |
| host process environments | yes | no | no |
| readable by the model's shell | yes | yes | **no: it sees only the token** |

- **Gateway (default).** The door also runs a plain-HTTP reverse proxy to the one provider. It refuses anything but the
  session token, strips auth headers, adds the real key for the shape (`x-api-key` or `Authorization: Bearer`) and
  forwards over TLS. The real key reaches the door **on its stdin only**. All five first-wave CLIs accepted an `http://`
  base and streamed through it.
- **Key file (fallback, `run.credential: "file"`).** For a CLI that needs `https://` or ignores the base URL. The model's
  shell can read it, so prefer the gateway.
- **Never** the key's value as an environment variable.
- **Every child gets an allowlist of environment variables, never a blocklist.** This development machine's shells,
  Docker daemon and containerd carry provider keys under several names; a blocklist leaked one on the first try. The
  container daemon in production must run without provider keys in its environment.

**Gateway fixes to make** (each with a test): a **stable URL and credential path for the whole session** (a network
alias, e.g. `http://hi-provider:8080`, and `/run/hi/key`): Hermes saves the URL with its session and its resume broke
when it changed; once headers have been relayed, an upstream error **only closes** the connection (today it can write a
502 into a started response); connection reuse (today one request per connection, which works but costs a TLS handshake
per call). No WebSocket support is needed by any harness yet.

---

## 8. The API

Resources (`PUT`, `GET` one or all, `DELETE`; none stream):
- **providers** `{name, url, key, api}`: the key is never returned.
- **harnesses**: a folder (its files as a JSON map of path → content); a PUT starts its install; `GET` shows
  `install: installing | ready | failed`.

Requests and sessions:

| Method | Path | Does | Streams |
|---|---|---|---|
| POST | `/responses` | standard OpenAI Responses: a new session, or `previous_response_id` to continue one | `stream: true` |
| GET | `/sessions` | every session, without its responses | no |
| GET | `/sessions/{id}` | the session with every response and its artifacts | `?stream=true` follows it until idle, across continuations |
| POST | `/sessions/{id}/interrupt` | `{input}`; degrades per §4.8; replies `{outcome, response}` | yes |
| POST | `/sessions/{id}/stop` | `{timeout_s?}`; SIGINT, then a kill; replies `{outcome: stopped \| killed \| idle, session}` | no |

- **`model`** names the harness, and optionally a provider and a model: `"claude-code"`, `"claude-code/claude-sonnet-4-6"`,
  `"claude-code@deepseek/deepseek-chat"`. A continued session stays on its harness and provider.
- **A response** is the OpenAI shape plus a `harness` object carrying every artifact by default: `session`, `name`,
  `provider`, `exit_code`, `latency_s`, `usage`, `cost_usd`, `resume`, `stdout`, `stderr`, `diff`, `changes` (path →
  new content, `null` if deleted), `files` (the whole tree after the response), `steers`, `stop`, `base`, `commit`.
- **A session**: `id`, `status` (`active` or `idle`), harness, provider, `interrupt`, `resume`, timestamps, the
  `interrupts` log, and its responses in order.
- **Stream events**: `response.created`, `harness.stdout`, `harness.stderr`, `harness.steer`, `session.interrupted`,
  `response.completed`.
- One response at a time per session: a second `POST /responses` while one runs is a 409 (interrupt instead).
- Errors: 400 (can't be done), 404 (unknown), 409 (busy), 422 (malformed); body `{"detail": "…"}`.

---

## 9. The code

Layers: each imports only from the layers below it; layers 0 to 5 use only the standard library; a test enforces both.
Every module opens with a docstring naming its layer and its promise.

| Layer | Module | Class or function, and its one job |
|---|---|---|
| 0 | `errors.py` | `Invalid`, `NotFound`, `Conflict` |
| 0 | `execution.py` | `Spec`; `Event`; `Outcome` (exited, timed out, stopped gracefully, killed, failed to start); `Execution` (events, send, end_input, **stop(timeout)**, kill, wait); `Runtime` |
| 1 | `runtimes/process.py` | `ProcessExecution`: the only code that spawns a process, pumps its output, writes its stdin, stops and kills it |
| 1 | `runtimes/local.py` | `LocalRuntime`, for developing a harness |
| 1 | `runtimes/docker.py` | `DockerRuntime`: the hardened `docker run` of §6.3, env by name from an allowlist, teardown; `Images` (base and harness images, built once) |
| 1 | `runtimes/door.py` | `Door`: CONNECT allowlist and the provider gateway, run in its own container |
| 2 | `workspace.py` | `Workspace`: git snapshots, diff, changes, files, read; `.home/`, `.git/` never listed (port the 1.x module and its tests) |
| 3 | `harness/folder.py` | `HarnessFolder`: load and validate a folder (closed schema, contract version, `hi_adapter.py` identity, provider URL rule) |
| 3 | `harness/install.py` | `Installer`: the install container, the tools cache (§6.2) |
| 3 | `harness/contract.py` | `prepare()` → `Spec` (env, line 1, `home/`, `files` with empty-render deletion); `collect()` → `Result`. The contract, written once |
| 3 | `harness/response.py` | `Response`: one response on a runtime: start, events, steer, stop, result |
| 4 | `store.py` | `JsonStore`; `Registry` (providers, harnesses) |
| 5 | `sessions.py` | `Session` record; `Sessions`: start, continue, interrupt (degrading), stop, follow, artifacts, undelivered steers, recover |
| 6 | `api/wire.py`, `api/app.py`, `api/config.py` | the Responses wire format; the routes; settings from the environment |

The library's public API is layers 0 to 5, so Python callers drive sessions with no server:

```python
sessions = Sessions(data_dir)
s = await sessions.start(Ask("claude-code", "Fix the failing test"))
async for event in sessions.follow(s.id):
    ...
await sessions.interrupt(s.id, "Stop; write DONE instead")
await sessions.stop(s.id)
```

---

## 10. Order of work

Test-driven throughout: each step starts with the tests that state its promise, including what must never happen, in the
lowest layer that can prove it. Port proven 1.x pieces with their tests rather than retyping them (`ProcessExecution`,
the door's CONNECT core, `Workspace`, `JsonStore`, the hardening flags, the layer test).

0. **Clear the branch** (§13), leaving a package skeleton, the layer test and CI.
1. **Execution and runtimes:** `Outcome` with stopped and killed; `ProcessExecution.stop`; `DockerRuntime` with `--init`
   and process-group signals; the environment allowlist; the door (CONNECT + gateway with a stable alias, key via stdin,
   the close-after-headers fix). Live Docker tests: SIGINT reaches a CLI started by `run.sh`; only the provider is
   reachable; the key is nowhere but the door.
2. **Base image and `Installer`:** cache miss and hit, the marker, deletion on failure, the lock, architecture in the key,
   install egress only, no secrets; `image.Dockerfile`.
3. **Workspace, `HarnessFolder`, the contract, `Response`:** with the template's stand-in harness (`tests/standin/`,
   from `prototype/foundation/template/`): line 1, steers, end of stdin, SIGINT, early and final `HI_OUTPUT`, empty
   `files` deletion, the URL rule.
4. **Store and `Sessions`:** sessions, one response at a time, interrupt's three outcomes, stop's three outcomes,
   undelivered steers continued, artifacts live and finished, recovery after a restart.
5. **The API:** every route, error and stream event; the OpenAI SDK creates and streams unchanged.
6. **The first-wave folders**, ported from `prototype/harnesses/` with the fixes in §12, and a live suite
   (`scripts/live.py`, promoted from the prototype's proof drivers, with a steer cue on a file condition, not line counts)
   run sandboxed on every provider shape each harness claims, Anthropic included.
7. **Docs, `VISION.md`, `AGENTS.md`, `CHANGELOG.md` 2.0.0, the installer**; merge to `main`.
8. **Second wave:** the other 18 harnesses, one pull request each, each passing the live suite (§12.2).

---

## 11. Tests

- **No Docker, keys or network needed** for the default suite: the stand-in harness, a fake `docker` on `PATH`, and
  `LocalRuntime` above layer 1. **`-m docker`** runs the real-daemon tests. Both run in CI.
- **Negative space has tests too:** a key on a command line, in `docker inspect`, in a log, record or workspace; a
  container or network left after any path; a session reaching a host it wasn't given; a second response in a busy
  session; a drifted `hi_adapter.py`; an unknown `harness.json` field or contract version; a stale `files` render; a
  steer sent after a stop.
- **Live suite** per harness (`scripts/live.py`), sandboxed, with real keys, both credential modes: a one-shot that
  follows its instructions; resume (remember a word, recall it); steer (count with pauses, steer after 3, expect the
  steer's file and far fewer than 30 numbers); stop then continue (the resumed run says what it was doing and how far);
  install miss then hit; a secret audit. Run before every release.
- Name each test for its promise; wait on events, never a fixed sleep.

---

## 12. Harness folders

### 12.1 First wave: changes from the prototype

All five: drop `HI_RESUME` and stdin `model`/`instructions`/`metadata` handling; take the model from `HI_MODEL`; apply
the provider URL rule (delete the URL guessing in pi and OpenCode); map `usage` to the five keys (Claude Code and Codex);
use the `hi_adapter.py` additions (§5); add `"contract": 1`, `run.credential`, `run.egress`.

- **Claude Code:** pin the latest at port time (2.1.304 proven); decide auto-memory (`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`,
  **Prove**).
- **Codex:** keep the three network-off settings and `unbounded_connection_retries=false`; ephemeral login over RPC.
- **pi:** `PI_OFFLINE=1`; the key file path written into `models.json` must be the stable one.
- **OpenCode:** ripgrep installed and hash-pinned in `install.sh`; the quiet switches; basic auth on its loopback server.
- **Hermes:** remove `repoint()` once the gateway URL is stable; `context_length` from the folder; `TIRITH_ENABLED=0`.

### 12.2 Second wave

The other 18: Aider, CheetahClaws, Cline, DeepSeek Harness, Gajae, Goose, Grok CLI, harness-engineering, J-Code, Kilo,
Kimi Code, MiMo, MiniMax Code, nanobot, OMP, OpenHands, OpenSquilla, Qwen Code. Each one's protocol, quiet switches,
key-on-disk hazards and adapter design are in `prototype/survey/<name>.md`, and the patterns in
`prototype/survey/SUMMARY.md`. Pin each at its latest release, including the four that used to come from vendor install
scripts (Goose, Grok, J-Code, Kimi). Weakest, worth deciding on when their turn comes: Aider (no shell tool), CheetahClaws
(terminal-rendered output), MiMo (unexplained start-up stalls), harness-engineering (needs a patch to its own code).

---

## 13. What is removed

- **Keeper:** `.keeper/`, `keeper.toml`, `docs/keeper-spec.md`, `.github/workflows/keeper*.yml`,
  `.github/actions/keeper-setup/`, its `CODEOWNERS` lines, `scripts/live_matrix.py`.
- **`hi`:** `frontend/cli/`, its tests and the `hi` entry point; the installer installs the server only.
- **The fat image:** `harness_interface/resources/default.Dockerfile`, `.github/workflows/sandbox-image.yml`,
  `.github/actions/sandbox-image/`, `scripts/latest_versions.py` (reworked later to read `install.sh` pins).
- **The 23 old harness folders** under `harnesses/`; the first wave returns rebuilt, the rest one at a time.
- **The `sandboxes` resource**, `routing.py` (one function in `Sessions`), the `artifacts` file convention, every
  `/responses/{id}/…` route, and `examples/build-loop/` (rewritten on the new API later).
- `prototype/` stays until the first wave is ported and passing, then goes.

---

## 14. Rules that must always hold

- No harness-specific code outside a harness folder. The server knows only the contract.
- A key never reaches an image, a tools directory, a command line, `docker inspect`, a record, a log, an API response or
  a workspace; under the gateway, not even the sandbox.
- Child environments come from an allowlist.
- A session reaches only its provider (and `run.egress`); an install reaches only `install.egress` and holds no secrets.
- A failure to start is an outcome, not an exception; only a caller's mistake raises (400, 404, 409).
- Output never waits on a reader.
- Paths are the same inside the sandbox and out.
- One response at a time per session. A response is never left running: a stop that hangs becomes a kill; a restart
  closes what was in flight.
- `.home/`, `.git/` and the server's own files are never listed, diffed or returned as the user's work.
- Teardown runs on every path, shielded.
- `POST /responses` stays standard OpenAI Responses.

---

## 15. Open issues and proofs still to run

- **Anthropic in the sandbox** after the credit ran out: pi (at all), Hermes (steer and stop), Claude Code (file-mode stop
  then continue). The owner is topping up the key; rerun the live suite then.
- **A steer that arrives after a turn ended**, end to end, with the server re-sending it (§4.7).
- **Stopping by end of stdin**: implemented in `hi_adapter.py`, never exercised by a real harness.
- **The `continued` and `responded` tiers with a real CLI**: force one folder to each and prove stop → continue.
- **`image.Dockerfile`** for a harness that needs OS packages; **request files**; **git workspaces** (and whether the
  base image keeps git); **MCP, skills and hooks** brought in `home/`.
- **Cost** on models outside a CLI's price list is wrong, missing or zero; revisit a server-side price table later.
- **arm64**: every tools directory so far is x86_64.

---

## 16. Risks

- **CLIs change fast.** Pin every version; run the live suite before each release; a folder that breaks falls back to
  `continued` or `responded` while it is fixed.
- **Steering lands at the CLI's next safe point**, after its current tool calls, and depends on the model: a model that
  batches many commands, or does everything in one, can't be steered until that batch ends. The docs must say so.
- **The gateway is a new trust point.** It holds every key for a session; it gets its own tests, runs locked down, and
  sees only one provider per session.
- **`hi_adapter.py` copies** must move together; the identity check is the guard.
- **The machine running the server** must not carry provider keys in the container daemon's environment.
