# Plan: sessions, interrupt and stop (harness-interface 2.0.0)

**Status: a plan, not built.** Agreed with the owner on 2026-10-20. Written so that whoever builds
it, person or agent, can do so from this file alone, with no memory of the conversation it came
from. Where something here is a decision, it is marked **Decided**: don't reopen it without the
owner. Where it still has to be checked, it is marked **Verify**.

Contents: 1 what and why · 2 the decisions · 3 how it works today · 4 the API · 5 the harness
contract · 6 how interrupt and stop work · 7 every layer and file to change · 8 the harness
folders · 9 order of work · 10 tests · 11 what must stay true · 12 risks.

---

## 1. What we are building, and why

**Today** a client sends a task to a harness (Claude Code, Codex, …) and waits. It can't say
anything while the harness works. Its only control is `POST /responses/{id}/cancel`, which kills
the container on the spot: the harness never saves, so the next request may start the CLI's
conversation from nothing, and whatever it was halfway through is lost. Reading what a turn
produced takes six more routes (`/output`, `/log`, `/diff`, `/files`, `/files/{path}`, and the
record itself).

**We want** harness-interface to feel like driving an interactive session, for any client:
- **start** a request, and get back the answer **with everything the request produced**;
- **check** on a session while it works, and see how its work evolves from request to request;
- **interrupt** it with new text: the text reaches the harness while it works where the harness
  supports that, and otherwise the work is stopped gracefully and continued with the text;
- **stop** it: gracefully, and killed only if it won't stop in time;
- **continue** it later, with the harness's own memory of the conversation intact.

**Why it matters:**
- No other harness platform we know of lets you steer a running harness across many harnesses
  through one interface. Others offer cancel and continue at best.
- `hi` becomes an interactive session over any harness: type to interrupt, Ctrl-C to stop.
- Programs can steer. The software factory (`mrcloudchase/software-factory-template`) can keep
  its loop running and push the owner's comments into the work in progress, which makes an
  always-on factory for any repository possible.
- A much smaller API: one OpenAI-standard route to request, and sessions for everything else.

**The principle that keeps it working as harnesses change:** the harness contract stays minimal
and generic, like a terminal. A harness gets input, prints output, can be given more text while
it works, and can be sent Ctrl-C (SIGINT). Every CLI understands that; we never commit to ACP,
JSON-RPC or any vendor's protocol. How a particular CLI takes text mid-work is that harness
folder's business, and changes there only.

---

## 2. The decisions (all **Decided** with the owner)

1. **Everything is a session.** A session is one harness, its workspace, the CLI's own
   conversation, and every response in it. The words "run", "turn" and "conversation" go from
   the API, the docs and `hi`. A **response** is one request's result, in the OpenAI Responses
   shape, because that is what OpenAI calls it.
2. **Requests stay standard OpenAI Responses:** `POST /responses`, streamed or not. Everything
   else is under `/sessions`.
3. **Every response carries all its artifacts by default:** stdout, stderr, diff, the changed
   files' contents, the file list, steers, usage, cost. No separate artifact routes.
4. **One route to interrupt:** `POST /sessions/{id}/interrupt` with text. It degrades by what the
   harness supports.
5. **A separate route to stop:** `POST /sessions/{id}/stop`. SIGINT, then a kill after a timeout.
6. **The contract adds one field:** `run.interrupt` in `harness.json`, with the value
   `"steered"`, `"continued"` or `"responded"` (default). See §5.
7. **Stream event names:** `harness.stdout` and `harness.stderr` (were `harness.output` and
   `harness.log`); new `harness.steer` and `session.interrupted`.
8. **Removed routes** (this is why it is 2.0.0): `GET /responses`, `GET /responses/{id}`,
   `POST /responses/{id}/cancel`, `/responses/{id}/output`, `/log`, `/diff`, `/files`,
   `/files/{path}`. The OpenAI SDK's `responses.create` (and streaming) keep working;
   `responses.retrieve` and `responses.cancel` stop working. Accepted.
9. **The owner amends the "closed contract" principle** once, for this: `VISION.md` principle 2
   and `AGENTS.md` principle 3 (both human tier) say the contract was extended once, with
   `run.interrupt`, stdin text lines and SIGINT, and is closed again.

**Recommended, confirm in phase 0:** rename the CLI's resume handle from "session" to "resume",
because "session" now means ours: `HI_SESSION_ID` → `HI_RESUME`, the `{session_id}` placeholder →
`{resume}`, the `HI_OUTPUT` key `session_id` → `resume`, and the record field → `harness.resume`.
Every shipped harness changes in the same release.

**Open, for the owner:** should a response list every file in the workspace after it
(`harness.files`)? This plan includes the list (cheap: every response is already a git commit) but
not the contents of unchanged files. Without the list, you can't tell what the whole tree looked
like at a given response.

---

## 3. How it works today (read before changing anything)

Version 1.0.5. The package is about 1,900 lines in layers; each layer imports only from those
below it, and `tests/test_layers.py` enforces it. `AGENTS.md` at the repository root explains the
layers, the rules and the conventions; read it first.

| Layer | Files | What matters here |
|---|---|---|
| 0 execution | `errors.py`, `execution.py` | `Spec(interactive=…)` keeps stdin open; `Execution.send()` and `end_input()` write to a running process. **Already built, unused above layer 1.** `Outcome` is `exited`, `timed_out`, `cancelled` or `failed`. |
| 1 runtimes | `runtimes/process.py`, `local.py`, `docker.py`, `egress.py` | `ProcessExecution` spawns in its own process group; `cancel()` sends SIGKILL to the group. Docker runs `docker run --rm -i …` (stdin reaches the container); cancel is `docker kill` (SIGKILL). |
| 2 workspace | `workspace.py` | a git repository per conversation. `snapshot()`, `changes()`, `diff(base, head)` (live when `head` is None), `files(commit)`, `read(path, commit)`. Enough for every artifact; no change needed. |
| 3 harness | `harness/contract.py`, `turn.py`, `template.py` | `prepare()` builds the `Spec`: request JSON (indented) on stdin, then stdin closed; `HI_*` variables. `collect()` reads `.hi/output.json` once, at the end. `Turn` starts, streams, cancels, snapshots. |
| 4 resources | `resources/registry.py`, `store.py` | `JsonStore` (one JSON file per item, written whole); providers, sandboxes, harnesses. |
| 5 routing | `routing.py` | `ByName`: `model` names the harness; a conversation stays on its harness. |
| 6 platform | `platform/service.py`, `records.py`, `runs.py`, `placement.py` | `Service` starts turns in the background, one per workspace at a time (`busy`); `Record` per turn (`records/{resp_id}.json`), with `workspace` and `session_id` (the CLI's handle); `Run` streams events to followers. |
| 7 api | `api/app.py`, `wire.py`, `config.py` | the routes; the OpenAI wire format; SSE events `response.created`, `harness.output`, `harness.log`, `response.completed`. |
| 8 client | `frontend/cli/hi_cli/main.py`, `api.py`, `daemon.py`, `harness.py` | `hi run`, `hi ls`, `hi show`, `hi output`, `hi log`, `hi diff`, `hi files`, `hi cancel`; Ctrl-C cancels. |

The 23 shipped harnesses are folders in `harnesses/`: `harness.json`, `run.sh`, `report.py`,
`artifacts` (a few have one more file). **Every `report.py` writes `HI_OUTPUT` only after the CLI
has finished**, so a killed request reports no resume handle; on a first request that loses the
CLI's conversation.

Callers of the routes being removed, which must change in the same release:
- `frontend/cli/hi_cli/api.py` (every response route);
- `examples/build-loop/loop.py` (`/files/{path}`, `/diff`, `/cancel`);
- `.keeper/engine/runtime.py` line ~88 (`/files/{path}`): human tier;
- outside this repository: `mrcloudchase/software-factory-template`, `.factory/loop.py` (reads
  files through `/responses/{id}/files/{path}`).

---

## 4. The API (2.0.0)

### 4.1 Routes

Resources do not change: providers, sandboxes and harnesses each have `PUT /{kind}/{name}`,
`GET /{kind}`, `GET /{kind}/{name}`, `DELETE /{kind}/{name}`. None stream.

| Method | Path | Request | Reply | Streams |
|---|---|---|---|---|
| POST | `/responses` | OpenAI shape: `{"model": "harness[/model]", "input": "…" or items, "instructions"?, "previous_response_id"?, "metadata"?, "stream"?}` | a **response** | yes, with `"stream": true` |
| GET | `/sessions` | — | `{"object": "list", "data": [session summaries]}` (a session without `responses`) | no |
| GET | `/sessions/{id}` | `?stream=true` to follow | a **session**; with `stream=true` and an active response, its events from the start | yes |
| POST | `/sessions/{id}/interrupt` | `{"input": "…" or items, "instructions"?, "metadata"?, "stream"?}` | `{"outcome": "steered" \| "continued" \| "responded", "response": <response to follow>}` | yes |
| POST | `/sessions/{id}/stop` | `{"timeout_s"?: 20}` | `{"outcome": "stopped" \| "killed" \| "idle", "session": <session>}` once nothing is running | no |

Rules:
- A new `POST /responses` (no `previous_response_id`) creates a session. With
  `previous_response_id`, it continues that response's session. While the session has a response
  in progress, it is a 409: interrupt instead.
- `interrupt` without a stream: when `steered`, it replies at once with the response in progress
  (follow it with `GET /sessions/{id}?stream=true`); when `continued` or `responded`, it replies
  when the new response ends, like `POST /responses`.
- `stop` replies only when the response has ended (gracefully, or killed after `timeout_s`).
- Errors as today: 400 (can't be done), 404 (unknown id), 409 (conflicts with something running),
  422 (bad body). Body `{"detail": "…"}`.

### 4.2 The response object

The OpenAI Responses shape, unchanged, plus everything harness-specific under `harness`:

```json
{
  "id": "resp_…", "object": "response", "created_at": 1792309774.1,
  "status": "completed",
  "model": "claude-code", "instructions": "…", "input": "…", "previous_response_id": null,
  "output": [{"type": "message", "role": "assistant", "status": "completed",
              "content": [{"type": "output_text", "text": "…the answer…", "annotations": []}]}],
  "usage": {…}, "error": null, "incomplete_details": null, "metadata": {},
  "harness": {
    "session": "sess_…",
    "name": "claude-code", "provider": "anthropic", "sandbox": "default",
    "runtime": "docker", "image": "harness-interface/default:…",
    "exit_code": 0, "latency_s": 21.1, "cost_usd": 0.12,
    "resume": "…the CLI's own resume handle…",
    "stdout": "…everything it printed on stdout…",
    "stderr": "…everything on stderr…",
    "diff": "…unified diff of this response's changes…",
    "changes": {"src/app.py": "…new content…", "old.py": null},
    "files": ["…every file in the workspace after this response…"],
    "steers": [{"at": 1792309780.2, "input": "…"}],
    "stop": null,
    "base": "<workspace commit before>", "commit": "<commit after>"
  }
}
```

- `status`: `in_progress`, `completed`, `failed`, `incomplete` (timed out) or `cancelled`
  (stopped, or ended by an interrupt).
- `harness.stop`: `null`, `"stopped"` (ended gracefully on request) or `"killed"`.
- While in progress, `stdout`, `stderr`, `diff`, `changes` and `files` are what exists so far
  (`Workspace.diff(base)` with no head is already live).
- `harness.changes` holds contents for text files; a binary file's value is
  `{"binary": true, "size": n}`. **Verify** this rule when building; keep it simple.

### 4.3 The session object

```json
{
  "id": "sess_…", "object": "session",
  "status": "active",
  "harness": "claude-code", "provider": "anthropic", "sandbox": "default",
  "runtime": "docker", "image": "…",
  "interrupt": "steered",
  "resume": "…latest resume handle…",
  "created_at": …, "updated_at": …,
  "usage": {…summed where numeric…}, "cost_usd": 0.41,
  "interrupts": [{"at": …, "input": "…", "outcome": "steered", "response": "resp_…"},
                 {"at": …, "outcome": "stopped", "response": "resp_…"}],
  "responses": [ …every response object, oldest first… ]
}
```

- `status`: `active` (a response is in progress) or `idle`.
- `interrupt`: the harness's `run.interrupt`, so a client knows what interrupt will do.
- Read `responses` in order to see how the work evolved: each has its `diff`, `changes`, `files`,
  `steers`, cost and the commits before and after.

### 4.4 Stream events (server-sent events)

| Event | Data |
|---|---|
| `response.created` | `{"type", "response": <response, in_progress>}` |
| `harness.stdout` | `{"type", "line": "…"}`, one per line on stdout |
| `harness.stderr` | `{"type", "line": "…"}`, one per line on stderr |
| `harness.steer` | `{"type", "input": "…", "at": …}`: text sent into the response, in order with its output |
| `session.interrupted` | `{"type", "outcome": "continued" \| "responded", "from": "resp_…"}`: sent before a continuation's `response.created` |
| `response.completed` | `{"type", "response": <the finished response>}` |

The `X-Response-Id` header stays on `POST /responses`; add `X-Session-Id`.

---

## 5. The harness contract (what a harness folder must do)

The contract lives in one place, `harness_interface/harness/contract.py` (its module docstring),
and is documented in `docs/users/harness-contract.md`. 2.0.0 adds three things and nothing else.

**1. `run.interrupt` in `harness.json`:** the best the harness can do when interrupted.

| Value | The harness promises | Interrupt does |
|---|---|---|
| `"steered"` | stdin stays open for the whole response; it reads it line by line and hands each line to its CLI while the CLI works | the text goes into the response in progress |
| `"continued"` | on SIGINT, it stops its CLI gracefully and reports its resume handle, so the next request resumes the CLI's conversation | stop gracefully, then a new response with the text, resuming |
| `"responded"` (default) | nothing more than today | stop (killed after the timeout), then a new response with the text in the same workspace; the CLI resumes only if a handle was reported |

**2. For `"steered"` only, stdin is a stream of lines:**
- line 1: the request (the same object as `.hi/request.json`), as one line of compact JSON;
- each later line: one JSON **string**, more text from the user (JSON so it can hold newlines);
- end of file: stop gracefully.
For every other value, stdin is as today: the request JSON, then closed. (This matters: many CLIs
read stdin to its end before starting, and would hang if it stayed open.)

**3. Stopping is SIGINT, for every harness.** The server sends SIGINT to the harness's whole
process group, waits up to the stop timeout (default 20 s), then kills it. A harness that handles
SIGINT stops cleanly; one that doesn't is killed. The response ends `cancelled` either way, with
`harness.stop` saying which.

**And a rule the shipped harnesses must follow** (allowed today, required now): write `HI_OUTPUT`
**as soon as the resume handle is known**, then again whenever more is known, each time atomically
(write `.hi/output.json.tmp`, then `os.replace`). The server reads it at the end, whatever ended
the response. A `report.py` must **ignore SIGINT** (`signal.signal(signal.SIGINT, signal.SIG_IGN)`)
so it keeps reading until its CLI has exited, then writes its final report.

---

## 6. How interrupt and stop work, step by step

**`POST /sessions/{id}/stop {timeout_s}`**
1. No response in progress → `{"outcome": "idle"}`.
2. Otherwise `Turn.stop(timeout_s)`: SIGINT to the process group (Docker: `docker kill --signal INT`,
   see §7.2), and a kill scheduled after `timeout_s`.
3. Wait for the response to end; its record finishes `cancelled` with `harness.stop` set.
4. Reply `stopped` or `killed`, with the session. Log it in the session's `interrupts`.

**`POST /sessions/{id}/interrupt {input}`**
1. Session idle → start a new response with `previous_response_id` = the session's last response.
   Outcome `continued`.
2. Session active and `interrupt == "steered"` → write the text as a line to the response's stdin
   (`Turn.steer`), add it to the response's `steers`, publish `harness.steer`. Outcome `steered`.
   - If the harness has already closed its stdin (it is finishing), fall through to step 3.
3. Session active, otherwise → stop it as above (`timeout_s` default), then start a new response
   with `previous_response_id` = the stopped one and the text. Publish `session.interrupted`.
   Outcome is the harness's value: `continued` or `responded`.
4. Log the interrupt in the session's `interrupts`.

The server always passes the latest resume handle it has. The tier only says what the harness
promises.

---

## 7. Every layer and file to change

Keep each layer's module docstring true; `tests/test_layers.py` must still pass, and layers 0 to
6 stay standard-library only.

### 7.1 Layer 0: `harness_interface/execution.py` (human tier)
- `Execution` protocol: add `stop(timeout_s: float) -> None`: ask it to end gracefully, and end
  it by force after `timeout_s`. Safe from any thread; nothing once it has ended.
- `Outcome`: a stopped execution is `cancelled`; add `graceful: bool = False` (meaningful only for
  `cancelled`) so the record can say `stopped` or `killed`. Keep the invariants in `__post_init__`.
- `NeverStarted.stop()`: does nothing.
- Tests: `tests/test_execution.py`.

### 7.2 Layer 1: `harness_interface/runtimes/` (human tier)
- `process.py` `ProcessExecution`: add `stop(timeout_s)`: call a `signal` callback (default:
  `os.killpg(pid, SIGINT)`), then schedule the existing `_end("cancelled")` after `timeout_s`.
  If the process exits before then, the outcome is `cancelled(graceful=True)`; otherwise
  `cancelled(graceful=False)`. `spawn()` gains an optional `signal` callable beside `kill`.
- `docker.py` `DockerRuntime.run_argv`: add `--init` and `-e TINI_KILL_PROCESS_GROUP=1`, so the
  container's init forwards signals to the whole process group. Without an init, the harness's
  first process (usually `bash run.sh`) is PID 1, which ignores signals it doesn't handle.
  **Verify** with a real Docker daemon that SIGINT reaches a CLI started by `run.sh` (a test in
  `tests/test_docker_live.py`). If the variable doesn't work, the fallback is
  `docker exec NAME kill -INT -1` as the container's user.
- `docker.py`: pass `signal=lambda: docker("kill", "--signal", "INT", names.run)` to `spawn`.
- `local.py`: nothing (the default `killpg` is right).
- `tests/fakes/docker`: handle `kill --signal INT` (send SIGINT to the recorded pid's group).
- Tests: `tests/test_runtimes.py` (a process that traps SIGINT and exits ends `cancelled`,
  graceful; one that ignores it is killed after the timeout; Docker argv has `--init`),
  `tests/test_docker_live.py`.

### 7.3 Layer 2: `harness_interface/workspace.py`
No change. `diff`, `files`, `read` and `changes` already give every artifact, at any commit, and
live.

### 7.4 Layer 3: `harness_interface/harness/` (`contract.py` is human tier)
- `contract.py`:
  - `Run`: add `interrupt: Literal["steered", "continued", "responded"] = "responded"`, validated.
  - `prepare()`: for `steered`, `Spec(interactive=True, input=json.dumps(body) + "\n")`;
    otherwise as today. Rename `HI_SESSION_ID` → `HI_RESUME`, placeholder `session_id` → `resume`
    (if the rename is confirmed, §2).
  - `Request.session_id` → `resume`; `Result.session_id` → `resume`; add
    `Result.stop: str | None` (`"stopped"` / `"killed"`).
  - `collect()`: read `resume` from `HI_OUTPUT`; if the outcome is `cancelled`, status
    `cancelled` and `stop` from `outcome.graceful`.
  - The module docstring: the three additions of §5, word for word with the docs.
- `turn.py` `Turn`:
  - `steer(text) -> None` (async): `Invalid` if the harness isn't `steered`; `Conflict` if the
    execution's input is closed; if the execution hasn't started yet (sandbox still building),
    queue the line and write it right after start, in order.
  - `stop(timeout_s)`: from any thread. While still setting up: cancel the start (as `cancel()`
    does today). Running: `execution.stop(timeout_s)`.
  - Keep `cancel()` (a hard stop) for internal use.
- `template.py`: no change.
- Tests: `tests/test_harness.py`.

### 7.5 Layer 4: `harness_interface/resources/`
- `registry.py`: nothing for harnesses (the new `Run` field comes with `Harness`).
- The session store uses `JsonStore` as is.

### 7.6 Layer 5: `harness_interface/routing.py`
No change: a continued session stays on its harness (the `conversation` argument becomes the
session's harness).

### 7.7 Layer 6: `harness_interface/platform/` (the biggest change)
- New `sessions.py`: the `Session` record, stored in `data/sessions/{sess_id}.json`: `id`,
  `harness`, `provider`, `sandbox`, `runtime`, `image`, `interrupt`, `workspace`, `resume`,
  `created_at`, `updated_at`, `responses` (ids, in order), `interrupts` (log). Mutable, like
  `Record`. Ids are `sess_` + 16 hex characters.
- `records.py` `Record` (a response): add `session`, `steers`, `stop`; `session_id` → `resume`;
  `workspace` stays (copied from the session) so a record stands alone.
- `runs.py` `Run`: publish `steer` events (a kind of their own, never written to the stdout/stderr
  files); keep `follow()`.
- `service.py` `Service`:
  - `start(ask)`: no previous id → a new session (workspace `data/workspaces/{sess_id}/`); with
    one → its session. One active response per session (`busy` keyed by session id; 409 otherwise).
  - `session(sid)`, `sessions()`: read the store; `session(sid)` assembles each response with its
    artifacts (§4.2).
  - `steer(sid, text)`, `interrupt(sid, ask) -> (outcome, Run)`, `stop(sid, timeout_s) -> outcome`:
    §6, step by step.
  - Artifacts: a function here (not in `api/`) that builds `stdout`, `stderr` (from `logs/`),
    `diff`, `changes`, `files` (from `Workspace`) for a record, live or finished.
  - `recover()`: as today, plus every session left `active` becomes `idle`.
  - **Migration from 1.x data:** at startup, records with no `session` are grouped by `workspace`
    into sessions (oldest response first), once. Test it with a 1.x-shaped data directory.
- Tests: `tests/test_platform.py`.

### 7.8 Layer 7: `harness_interface/api/`
- `app.py`: keep the resource routes and `POST /responses`; remove the response routes listed in
  §2.8; add `GET /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/interrupt`,
  `POST /sessions/{id}/stop`. Each route validates, calls `Service`, shapes the reply: nothing else.
- `wire.py`: `response()` with the §4.2 fields; `session()`; `InterruptRequest`, `StopRequest`;
  `stream()` with the renamed and new events (§4.4); the stream of an interrupt (same response,
  or `session.interrupted` then the new one).
- `config.py`: nothing (the stop timeout default is a constant in the platform).
- Tests: `tests/test_api.py`, including the OpenAI SDK test (`responses.create` and streaming
  still work; drop `retrieve`).

### 7.9 Layer 8: `frontend/cli/hi_cli/`
- `api.py`: one method per route of §4.1.
- `main.py`:
  - `hi run HARNESS "task"`: as today. On a terminal, for a harness whose `interrupt` is
    `steered`, each line typed while it works is sent with `interrupt` (shown as `» …`); for
    the others, a typed line interrupts too (it stops and continues). First Ctrl-C: `stop`;
    second Ctrl-C: `stop` with `timeout_s` 0. `--detach` prints the session id.
  - `hi run -c [SESSION] "text"`: continue the last session (or the one named).
  - `hi interrupt SESSION "text"`, `hi stop SESSION [--timeout S]`.
  - `hi ls`: sessions. `hi show SESSION`: the session. `hi show SESSION --stdout | --stderr |
    --diff | --files | --file PATH [--response ID]`: one part (default: the latest response).
  - Remove `hi output`, `hi log`, `hi diff`, `hi files`, `hi cancel`.
  - `daemon.HOME / "last-response"` → `last-session`.
- Tests: `tests/test_cli.py`.

### 7.10 Everything else in this repository
- `harnesses/*`: §8.
- `tests/echo/`: report `resume`; a new `tests/steer/` stand-in harness (§10).
- `examples/build-loop/loop.py`: read `changes` and `diff` from the response; stop with
  `/sessions/{id}/stop`. `examples/library/run_a_harness.py`: `--session` → `--resume`.
- `scripts/live_matrix.py`: works as is (it only uses `POST /responses`); add
  `scripts/live_interrupt.py` (§10).
- `.keeper/engine/runtime.py`: read files from the response's `changes` instead of
  `/files/{path}` (human tier: the owner approves). `.keeper/tests/` as needed.
- Docs, all of `docs/users/` (api, api-clients, cli, harness-contract, harnesses, how-it-works,
  getting-started, library, loops, troubleshooting) and `docs/contributors/` (architecture,
  extending, testing), `README.md`, `AGENTS.md` (human tier), `VISION.md` (human tier),
  `harnesses/README.md`.
- `CHANGELOG.md`: `## [2.0.0]`, saying what was removed and what replaces it.

### 7.11 Outside this repository, in the same release window
- `mrcloudchase/software-factory-template`, `.factory/loop.py`: read files from `changes`; later,
  forward the owner's comments with `interrupt` while an agent works.
- Its `factory.yml` pins `HI_VERSION`; move it to 2.0.0 only together with that change.

---

## 8. The harness folders

Everything here is per folder; the server knows none of it. Versions are the ones pinned in
`harness_interface/resources/default.Dockerfile` on 2026-10-19 (CLIs installed by their vendors'
scripts are "latest"). Each protocol detail was read from that version's source by research on
2026-10-19; **Verify** each against the pinned version before building (`--help`, and the schema
for RPC modes), because CLIs change.

### 8.1 Every harness: report early, survive SIGINT (makes most of them `continued`)
In each `report.py`: ignore SIGINT; write `HI_OUTPUT` atomically the moment the resume handle
appears, and again at the end. Where a CLI prints its handle late, fix it in the folder:

| Harness | Resume handle, early | Graceful on SIGINT (research) |
|---|---|---|
| Claude Code | `system`/`init`, or choose with `--session-id <uuid>` | transcript appended every ~100 ms; resumes from the last message |
| Codex | `thread.started`, the first event | yes: interrupts the turn, closes its log |
| pi, OMP, Gajae | the `session` header, first line | OMP yes; pi and Gajae save per message (Gajae: nothing before the first reply) |
| DeepSeek Harness | the `session` event, first | yes (5 s shutdown) |
| MiniMax Code | `session.started`, early | yes |
| OpenCode, Kilo, MiMo | the first `step_start` | saved per message (SQLite) |
| Qwen Code | `system`/`init`, or `--session-id` | appended per record |
| Goose | name it: `-n NAME`, resume `-r -n NAME` | yes; saved per message |
| Grok CLI | choose it: `--session-id <uuid>` on a first request | yes ("saved up to the last completed tool call") |
| J-Code | switch `run --json` to `run --ndjson` (first event `start`) | saved per message and tool batch |
| Hermes | printed at the end or on SIGINT (stderr, already piped to `report.py`) | yes |
| Kimi Code | at the end only; recover with `kimi session list --json` | yes |
| nanobot, OpenSquilla, Aider, harness-engineering | `run.sh` already knows it (minted, chosen or constant): write it first | nanobot/OpenSquilla save at checkpoints; Aider's history file |
| Cline | from `session/new` in `acp.py` | nothing saved before the first reply |
| OpenHands | printed on exit; else its newest conversation folder | one file per event |
| CheetahClaws | on `/exit` (already fed after the task) | interrupted mid-response, keeps history |

Then set each folder's `run.interrupt`: `"continued"` where a live check (§10) shows that a
stopped response resumes with its conversation; otherwise leave `"responded"`.

### 8.2 `steered` harnesses: an adapter in the folder
A steered folder runs `exec python3 "$HI_HARNESS_DIR/adapter.py"` from `run.sh`, after mapping the
provider as today. `adapter.py` (standard library only):
1. reads line 1 (the request);
2. starts the CLI in its steerable mode **in its own process group** (so SIGINT reaches the
   adapter, which turns it into the CLI's graceful stop);
3. passes the CLI's output through to stdout, flushed, line by line, and writes `HI_OUTPUT` early
   and at the end;
4. turns each later stdin line into the CLI's own "more input" call;
5. on SIGINT or end of stdin: the CLI's graceful stop, wait, write `HI_OUTPUT`, exit;
6. when the CLI's work ends with no text still pending: write `HI_OUTPUT`, close the CLI, exit 0.

Shared code goes in `hi_control.py`, copied identically into every steered folder, with a test that
every copy is the same (as the artifacts block in `run.sh` is tested today). Folders stay
self-contained.

**First: the six ready ones** (they include the four most-used harnesses by monthly installs on
2026-10-19: Codex 91.5M, Claude Code 49.1M, pi 16.6M, OpenCode 11.6M):

| Harness | Steerable mode | More text | Graceful stop | Notes |
|---|---|---|---|---|
| Claude Code | `claude -p --input-format stream-json --output-format stream-json --verbose --dangerously-skip-permissions --replay-user-messages` | a stdin line `{"type":"user","message":{"role":"user","content":TEXT},"parent_tool_use_id":null}` (the task is the first such line, not an argument) | `{"type":"control_request","request_id":ID,"request":{"subtype":"interrupt"}}`, then close its stdin | text lands after the current tool results; done = a `result` event with every sent line echoed back (`isReplay`) |
| Codex | `codex app-server` (JSON-RPC on stdio; marked experimental) | `turn/steer {threadId, expectedTurnId, input}` | `turn/interrupt {threadId, turnId}` | `initialize` → `thread/start` or `thread/resume` → `turn/start`. **Verify** the approval and sandbox parameters (it must never ask). |
| pi | `pi --mode rpc --provider P --model M --session-id ID` | `{"type":"steer","message":TEXT}` | `{"type":"abort"}` | first `{"id":"1","type":"prompt","message":TASK}`; done at `agent_settled` |
| OMP | `omp --mode rpc --approval-mode yolo --model anthropic/M` | `{"type":"steer","message":TEXT}` | `{"type":"abort"}` | `PI_PROXY` as today. **Verify** how RPC mode reports the session id. |
| OpenCode | start `opencode serve --port P --hostname 127.0.0.1` in the container; `POST /session` (id at once) or reuse the handle; stream with `opencode run --attach http://127.0.0.1:P --dir WS --format json -m M -s ID TASK` | `POST /session/{id}/prompt_async?directory=WS` `{"model":{…},"parts":[{"type":"text","text":TEXT}]}` | `POST /session/{id}/abort` | proven end to end against a stand-in model; stop `serve` at the end |
| Kilo Code | as OpenCode, with `kilo serve` | as OpenCode | as OpenCode (`?scope=tree` default) | signal the native binary, not the npm wrapper |

**Then, one at a time, after resolving its caveat:**

| Harness | Steerable mode → more text / stop | Resolve first |
|---|---|---|
| MiMo Code | `mimo serve` → `prompt_async` / `abort` (proven) | never its ACP mode (drops mid-work text); a disconnected client stops its work |
| MiniMax Code | `mcode acp` → `mcode/session/steer` / `session/cancel` | the method's exact wire name |
| Gajae Code | `gjc --mode acp` → `_gjc/sdk/control` `turn.steer` / `session/cancel` | its helper broker process in Docker |
| J-Code | `jcode api-bridge --stdio` → `soft_interrupt` / `cancel` | stop its background daemon at the end |
| Goose | `goose acp` → `_goose/unstable/session/steer` / `session/cancel` | marked unstable |
| Hermes | `hermes acp` → a prompt `/steer TEXT` / `session/cancel` | the image needs `hermes-agent[acp]` |
| Kimi Code | `kimi web --no-open` → REST `prompts` then `:steer` / `:abort` | the installer now ships 2.2.0, a rewrite: check the current folder still works at all |
| Qwen Code | `qwen --acp`; the adapter answers its `craft/drainMidTurnQueue` callback / `session/cancel` | the callback's contract |
| nanobot | `nanobot gateway` + WebSocket / `/stop` | the message format |
| OpenSquilla | `opensquilla gateway run` → `sessions.steer.v2` / `sessions.abort` | gateway auth; very few users |
| Grok CLI | `grok agent --always-approve stdio` → `x.ai/interject` / `session/cancel` | the method's name and parameters |

**Not steerable** (stay `continued` or `responded`): Cline (its steering exists only behind its
hub daemon), DeepSeek Harness, OpenHands (mid-work text over ACP is racy), Aider, CheetahClaws,
harness-engineering (ours: could become steered later by reading stdin between tool calls).

---

## 9. Order of work

Build on a branch `v2` from `main`; merge to `main` (and so release 2.0.0) only when every phase
through 6 is done, because the API change breaks clients.

0. **The owner's decisions:** approve this plan; reword `VISION.md` principle 2 and `AGENTS.md`
   principle 3; confirm the resume rename and the file list (§2).
1. **Graceful stop** (§7.1, §7.2), with the live Docker check of SIGINT through `--init`.
2. **The contract and `Turn`** (§7.4), the echo and steer stand-ins, and §8.1 for all 23 folders
   (report early, ignore SIGINT, rename).
3. **Sessions** (§7.7), with the 1.x migration.
4. **The API and `hi`** (§7.8, §7.9), the examples and Keeper's runtime (§7.10).
5. **The six ready steered harnesses** (§8.2) and `scripts/live_interrupt.py`; set each folder's
   `run.interrupt` from live results.
6. **Docs and `CHANGELOG.md` 2.0.0** (§7.10); release; then the factory (§7.11).
7. **The caveat harnesses**, one pull request each (2.x minor releases).

---

## 10. Tests

Each in the lowest layer that proves it (see `docs/contributors/testing.md`); name each test for
its promise; wait on events, never a fixed sleep.

- **Stand-in harness `tests/steer/`** (Python, standard library, `run.interrupt: "steered"`):
  reports a resume handle at once; "works" in steps (prints a line, a short wait); between steps
  reads any stdin lines and prints `{"steered": TEXT}`; on SIGINT or end of stdin writes
  `HI_OUTPUT` and exits 0. Request metadata `{"ignore_sigint": true}` makes it ignore SIGINT, to
  test the kill after the timeout.
- **Layer 0/1:** stop is graceful when the process handles SIGINT, a kill after the timeout when
  it doesn't; nothing is left (Docker fake and live); stop after the end changes nothing.
- **Layer 3:** a steered harness gets one line and an open stdin; others get today's input,
  closed; text sent before start arrives after line 1, in order; steering a non-steered harness is
  `Invalid`, after the end `Conflict`; a stopped response is `cancelled` with `stop` and its
  resume handle; the resume handle reaches the next request as `HI_RESUME`.
- **Layer 6:** a request makes a session; continuing adds to it; one active response per session;
  interrupt's three outcomes, and idle → continued; stop's three outcomes; steers and interrupts
  are on the records; artifacts are complete, live and finished; sessions left active at a
  restart become idle; 1.x data migrates.
- **Layer 7:** every route and error in §4; stream events and their order, including
  `harness.steer` among the output and `session.interrupted` before a continuation; the OpenAI SDK
  creates and streams.
- **Layer 8:** `hi run`, `-c`, `interrupt`, `stop`, `ls`, `show` and its parts.
- **Live, by hand, with real keys:** `scripts/live_interrupt.py`, for every harness with a key:
  - interrupt: ask it to count from 1 to 30 into `count.txt` with `sleep 1` between numbers; after
    5 numbers interrupt with "stop counting and write DONE to done.txt"; pass if `done.txt`
    exists, and report the outcome;
  - stop and continue: same task, stop after 5 numbers, then interrupt with "what were you doing,
    and how far did you get?"; pass if the answer names the counting and a number (this decides
    `continued` vs `responded`).

---

## 11. What must stay true

- The server has no code for any particular harness. It knows only: a harness may take text lines
  on stdin while it works (`steered`), and stopping is SIGINT, then a kill.
- A key never reaches a command line, a record, a log or an API response.
- One response at a time per session. A response is never left `in_progress`: a stop that hangs is
  a kill after the timeout; a restart closes what was in flight.
- `.hi/`, `.home/`, `.git/` and `__pycache__/` are never listed, diffed or returned in artifacts.
- `POST /responses` stays standard OpenAI Responses.
- Layers import only downward; layers 0 to 6 use only the standard library.
- A harness that declares nothing (`responded`) behaves exactly as in 1.x, except that it is now
  sent SIGINT before the kill.

## 12. Risks

- **CLIs change their protocols.** Codex's app-server and Goose's steer call are marked
  experimental or unstable. Pin versions, run `live_interrupt.py` before every release; a folder
  can always fall back to `continued`.
- **"Mid-work" means at the CLI's next safe point,** after its current tool calls, before its next
  model call. A long command is not cut short by a steer (only Gajae, and J-Code with `urgent`,
  abort running tools).
- **Text can race the end of a response.** Handled by §6 step 2 falling through to stop and
  continue.
- **Large responses.** `stdout` of a long response can be megabytes. Decided: everything by
  default. If it hurts, add OpenAI's own `include` query parameter later to trim; don't change the
  default.
- **Size budget.** `keeper.toml` caps the package near 2,000 lines; it is about 1,870 today. The
  sessions layer will push past it: plan to simplify elsewhere or have the owner raise the budget.
- **SIGINT in Docker** depends on `--init` forwarding to the group (§7.2). Prove it first, in
  phase 1.
