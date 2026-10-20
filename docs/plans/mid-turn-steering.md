# Plan: steer a running turn, and cancel without losing the conversation

Status: **a plan, not built.** Written 2026-10-20 from research on the CLI versions pinned in
`harness_interface/resources/default.Dockerfile` at that date. Whoever builds it (person or agent)
should be able to do so from this file alone; nothing here relies on remembering the conversation
it came from.

---

## 1. What we are building, and why

Today a turn is fire-and-forget. A client sends a task, the harness runs to the end, and the only
way to change its mind is `POST /responses/{id}/cancel`, which kills the container. Then:
- the harness never gets to save anything, so the next turn may start a fresh conversation;
- whatever it was halfway through is lost;
- the person or program driving it can't say "no, do it this way instead" while it works.

Interactive tools (Claude Code in a terminal, for example) let a person **type while the agent
works**: the message lands in the running turn at the next safe point, and Esc stops the turn
without losing the conversation. We want that for every harness that can support it, through the
one API, so that:
- `hi` can be driven like an interactive session: type to steer, Ctrl-C to stop, keep going;
- programs can steer: a software-factory loop forwards the owner's comments into the turn that is
  working right now, instead of waiting for it to end. With a long-running loop, that makes an
  always-on factory for any repository;
- no other harness platform we know of does this. Others let you cancel and continue; none lets
  you steer a running turn across many harnesses through one interface.

**Three capabilities, one interface:**

| Capability | What the client does | What happens |
|---|---|---|
| **Request** | `POST /responses` (exists) | a turn starts |
| **Steer** | `POST /responses/{id}/steer` (new) | the text reaches the running turn at its next safe point (after the current tool calls, before the next model call); the turn continues with it |
| **Cancel and continue** | `POST /responses/{id}/cancel` (exists; gains graceful stop and `wait`), then `POST /responses` with `previous_response_id` | the turn stops cleanly, its session and partial work are kept, and the next turn resumes the same conversation |

Harnesses fall into three tiers, decided by what their CLI can do natively. We never fake a
capability inside a harness; the tier is declared, and clients adapt.

| Tier | Steer | Cancel | Continue after cancel |
|---|---|---|---|
| **A: steerable** | native, into the running turn | graceful: the CLI stops the turn itself and saves | resumes with the partial work |
| **B: interruptible** | not available; clients use cancel and continue instead | graceful | resumes |
| **C: neither** | not available | a hard kill ends the turn | best effort: resumes from the last turn the CLI saved, if it reported its session early |

---

## 2. How it works today (read this first)

The relevant code, all in this repository:

- `harness_interface/execution.py`: `Spec` has `interactive: bool`; `Execution` has `send(data)` and
  `end_input()`. **The bottom layer already supports writing to a running process.** Nothing above
  it uses this. Tested by `test_more_input_while_it_runs` in `tests/test_runtimes.py`.
- `harness_interface/runtimes/process.py`: `ProcessExecution` keeps stdin open when
  `interactive=True`; `cancel()` sends SIGKILL to the process group.
- `harness_interface/runtimes/docker.py`: every run is `docker run --rm -i …`, so stdin reaches the
  container. Cancel is `docker kill` (SIGKILL).
- `harness_interface/harness/contract.py`: `prepare()` builds the `Spec`. It writes the request JSON
  (indented) to stdin and does **not** set `interactive`, so stdin closes right after. `collect()`
  reads `.hi/output.json` (`HI_OUTPUT`) once, at the end, even after a cancel.
- `harness_interface/harness/turn.py`: `Turn.cancel()` cancels the execution. No way to send input.
- `harness_interface/platform/records.py`: `Record.finish()` keeps the previous turn's `session_id`
  when a turn reports none (`self.session_id = result.session_id or self.session_id`).
- `harness_interface/platform/service.py`: `Service.cancel(rid)` returns at once; the turn ends in
  the background.
- `harness_interface/api/app.py`, `api/wire.py`: `POST /responses/{id}/cancel` → `{"cancelled": bool}`.
- `frontend/cli/hi_cli/main.py`: Ctrl-C during `hi run` calls cancel.
- Every shipped `harnesses/*/report.py` writes `HI_OUTPUT` **only when the CLI has finished**. A
  killed turn therefore reports no session id; if it was the first turn, the conversation is lost
  (the next turn starts the CLI fresh over the same files). A later turn falls back to the previous
  turn's session id.

The principle that matters: **the server knows nothing about any particular harness.** Each harness
is a folder (`harness.json`, `run.sh`, `report.py`, `artifacts`). That stays true: the server learns
one generic thing (a turn can take more input), and each harness folder translates it for its CLI.

---

## 3. The design

### 3.1 The contract change (the only one)

`harness/contract.py` and `AGENTS.md` say the contract is closed. This plan **amends it once,
deliberately**, and the amendment must be approved by the owner (it is human tier in
`keeper.toml`; `VISION.md` principle 2 and `AGENTS.md` principle 3 must be reworded to name it).
It adds no environment variable and no placeholder. It adds:

1. **One `harness.json` field: `run.interactive`** (bool, default `false`).
   - `false`: exactly today's behaviour. stdin carries the request JSON and is closed.
     (Required: many CLIs read stdin to end-of-file before they start, and would hang forever if it
     stayed open: `opencode run`, `pi -p`, `codex exec`, and others.)
   - `true`: the harness promises to read stdin **line by line** for the whole turn, and to act on
     the control lines below. The server keeps stdin open until the process exits.

2. **The stdin protocol for interactive harnesses**: newline-delimited JSON, one object per line.
   - Line 1: the request, the same object as `.hi/request.json`, on one line (compact JSON).
   - Then, at any time while the turn runs, zero or more of:
     - `{"type": "steer", "id": "stz_…", "text": "…"}`: deliver this text into the running turn, as
       the user, at the CLI's next safe point. If the CLI's turn has already ended, the harness may
       run it as a continuation in the same process (preferred) or exit and let the server refuse
       later steers.
     - `{"type": "interrupt", "id": "int_…"}`: stop the current turn the CLI's own graceful way, make
       sure the session is saved, write `HI_OUTPUT`, and exit.
   - End of file on stdin: treat as `interrupt`.
   - Unknown `type`: ignore (so the protocol can grow without breaking harnesses).

3. **`HI_OUTPUT` may be written many times.** The server reads it at the end, whatever ended the
   turn. A harness should write it **as soon as it knows the session id**, and again whenever it
   learns more, each time atomically (write a temporary file in `.hi/`, then `os.replace`), so a
   hard kill never leaves half a file and never loses the session. This is allowed by the contract
   today; the change is to require the early write in the docs and in every shipped harness.

4. **Status after an interrupt is `cancelled`.** If the server asked the turn to stop, the record
   ends `cancelled` even if the harness then exited 0. (Today `collect()` decides `cancelled` only
   from the execution outcome, which would be `exited(0)` after a graceful stop.)

Write the protocol down once, in `harness/contract.py`'s module docstring and in
`docs/users/harness-contract.md`, and nowhere else.

### 3.2 Library (`harness_interface/harness/turn.py`, `contract.py`)

- `prepare()`: when `harness.run.interactive`, build the `Spec` with `interactive=True` and
  `input=json.dumps(request_body) + "\n"` (compact, one line). Otherwise unchanged (indented, closed).
- `Run` dataclass in `contract.py`: add `interactive: bool = False`.
- `Turn.steer(text) -> str` (async): returns the steer id.
  - Raises `Invalid` if the harness is not interactive ("harness 'x' takes no input while it runs;
    cancel it and continue instead").
  - Raises `Conflict` if the turn has ended (the execution's input is closed).
  - If the execution has not started yet (the sandbox is still building), queue the line and write
    it right after the request line once it starts. Keep order.
- `Turn.cancel(grace_s: float | None = None)`: safe from any thread, as now.
  - Interactive harness: send `{"type": "interrupt"}`, mark the turn as cancel-requested, and after
    `grace_s` (default 20 s) cancel the execution hard if it is still running.
  - Not interactive: as today, a hard kill at once.
  - While still setting up: as today, the harness never starts.
- `collect()` (or `Turn._finish`): if cancel was requested, the `Result.status` is `cancelled`,
  whatever the exit code, and the reported `session_id`, `usage`, `cost_usd` and `answer` are still
  read. Files are still snapshotted (they already are).
- No change to layers 0 to 2: `Spec.interactive`, `Execution.send` and Docker's `-i` already do
  what is needed.

### 3.3 Platform (`harness_interface/platform/`)

- `Record`: add `steers: list[dict]` (`{"id", "text", "at"}`, in order), so every steer is on the
  record. Add `interactive: bool`, copied from the harness at start, so clients know whether the
  turn can be steered.
- `Service.steer(rid, text) -> dict`: find the live run (else `Conflict`: "response x is not
  running"), call `run.turn.steer`, append to the record, save the record, publish a `steer` event
  to followers, return `{"id", "text", "at"}`.
- `Service.cancel(rid, wait: bool = False) -> Record | bool`: as today; with `wait=True` it awaits
  the run's `done` and returns the final record, so a client can continue at once without a 409.
- `Run.publish`: steer events go to followers as their own event kind (not stdout or stderr), and
  are not written to the `.out`/`.log` files.

### 3.4 API (`harness_interface/api/`)

| Method | Path | Body | Reply |
|---|---|---|---|
| POST | `/responses/{id}/steer` | `{"input": "text"}` (also accept the list-of-items shape, text only) | 200 `{"id", "text", "at"}`; 400 if the harness isn't interactive; 409 if the turn isn't running; 404 unknown id |
| POST | `/responses/{id}/cancel` | optional `{"wait": true}` | without `wait`: `{"cancelled": bool}` (unchanged); with `wait`: `{"cancelled": bool, "response": <final record>}` |

- `wire.response()`: add `harness.steers` and `harness.interactive`.
- SSE: a new event `harness.steer`, `{"type": "harness.steer", "id", "text"}`, in order with the
  harness's own output, so a follower sees where in the turn each steer was sent.
- Continue stays `POST /responses` with `previous_response_id`: no new endpoint.

### 3.5 `hi` (`frontend/cli/hi_cli/`)

- `hi steer ID "text"`.
- `hi cancel ID [--continue "text"]`: graceful cancel with `wait`, then, if `--continue`, a new turn
  with `previous_response_id`, streamed like `hi run`.
- `hi run` on a terminal, for an interactive harness: while the turn streams, each line the person
  types is sent as a steer (shown dimmed as `» steered: …`). First Ctrl-C: graceful cancel, and
  `hi` offers to continue ("type to continue the conversation, Enter on an empty line to stop").
  Second Ctrl-C: hard cancel. For a non-interactive harness, typing during a run prints "this
  harness can't be steered; Ctrl-C, then continue".
- `api.py`: `steer()`, `cancel(wait=)`.

### 3.6 A client recipe that "feels like steering" on every tier

Document this (in `docs/users/api-clients.md`) and use it in loops:

```
try:   POST /responses/{id}/steer {"input": text}              # tier A, turn still running
except 400 or 409:                                               # tier B/C, or the turn just ended
       POST /responses/{id}/cancel {"wait": true}               # graceful where the CLI allows
       POST /responses {"model": …, "input": text, "previous_response_id": id}
```

---

## 4. Harness by harness

### 4.1 How an interactive harness folder is built

Same four files, plus an adapter:

- `harness.json`: `"run": {"interactive": true, …}`.
- `run.sh`: maps the provider onto the CLI's settings as today, then
  `exec python3 "$HI_HARNESS_DIR/adapter.py"`.
- `adapter.py` (standard library only, runs in the sandbox):
  1. Read line 1 of stdin: the request.
  2. Start the CLI in its steerable mode (below) as a child process.
  3. Thread A, the CLI's output: pass every line through to stdout unchanged and flushed (as
     `report.py` does today); recognise the session id, the end of the turn, usage, cost and the
     answer; write `HI_OUTPUT` atomically the moment the session id is known, and again at the end.
  4. Thread B, our stdin: for each control line, translate `steer` and `interrupt` into the CLI's
     own call. EOF = interrupt.
  5. When the CLI's turn ends and no steer is still pending: write `HI_OUTPUT`, stop the CLI
     cleanly (close its stdin, or its shutdown call, then wait, then kill), exit 0.
  6. On interrupt: send the CLI's native interrupt, wait up to ~15 s for it to settle, write
     `HI_OUTPUT`, stop the CLI, exit. The server's own grace (20 s) is the backstop.
- `hi_control.py`: a small shared helper (read control lines, atomic `HI_OUTPUT` write, pass-through
  writer), **copied identically** into every interactive folder, with a test that every copy is the
  same, exactly as the shared artifacts block in `run.sh` is tested today
  (`test_every_shipped_harness_puts_dropped_artifacts_in_place`). Folders stay self-contained; the
  server still has no harness code.

The CLIs' own state lives under `$HOME` (the workspace's `.home`), as today, so a session saved by
one turn's process is there for the next turn's.

### 4.2 Tier A, ready: build these first

These six cover the four most-used harnesses (by monthly installs on 2026-10-19: Codex 91.5M,
Claude Code 49.1M, pi 16.6M, OpenCode 11.6M). Every protocol detail below was read from the pinned
version's source; **re-verify each against the pinned version before building** (run its `--help`,
and for app-server or RPC modes, its schema), because CLIs change their protocols.

**Claude Code** (`@anthropic-ai/claude-code@2.1.42`). The smallest change: same process, different flags.
- Start: `claude -p --input-format stream-json --output-format stream-json --verbose
  --dangerously-skip-permissions --replay-user-messages [--model M]` plus `--resume ID` to continue,
  or `--session-id <new uuid>` on a first turn (so the id is known before anything runs; write
  `HI_OUTPUT` at once).
- The task is **not** an argument: send it as the first stdin line:
  `{"type":"user","message":{"role":"user","content":TASK},"parent_tool_use_id":null}`.
- Steer: another line of the same shape. The CLI queues it and attaches it before the next model
  call, after the current tool results. If the model had finished, it runs as the next turn in the
  same process.
- Interrupt: `{"type":"control_request","request_id":"<id>","request":{"subtype":"interrupt"}}`;
  wait for the matching `control_response`, then close the CLI's stdin.
- End of turn: a `result` event with no steer pending. With `--replay-user-messages`, each consumed
  user message is echoed back (`"isReplay": true`); pending = steers sent minus echoes seen.
- Session: `system`/`init` carries `session_id`. The transcript is appended to
  `$HOME/.claude/projects/…/<id>.jsonl` about every 100 ms, so a hard kill loses at most the
  message in flight.

**Codex** (`@openai/codex@0.163.0`). Moves from `codex exec` to `codex app-server` (JSON-RPC over
stdio; the app-server is marked experimental, so pin carefully).
- Start: `codex app-server` with `CODEX_HOME` as today (still `codex login --with-api-key` first).
- Requests: `initialize`; then `thread/start` (new) or `thread/resume {threadId}` (continue); then
  `turn/start {threadId, input: [{type: "text", text: TASK}]}`.
- Steer: `turn/steer {threadId, expectedTurnId, input: [...]}` → appended to the in-flight turn;
  fails if there is no active turn.
- Interrupt: `turn/interrupt {threadId, turnId}` → the turn ends with status `interrupted`.
- Session: the thread id from `thread/start`, before the turn starts. Rollout JSONL is flushed per
  item.
- To verify: the parameters for approvals and the sandbox (the app-server asks for approvals that
  `exec --dangerously-bypass-approvals-and-sandbox` used to skip; set "never ask" and full access,
  since our container is the sandbox). Generate the schema from the pinned binary to confirm field
  names.

**pi** (`@earendil-works/pi-coding-agent@1.3.0`).
- Start: `pi --mode rpc --provider anthropic --model M --session-id ID` (a new uuid on a first turn;
  pi creates the session on first use).
- Prompt: `{"id":"1","type":"prompt","message":TASK}`.
- Steer: `{"type":"steer","message":TEXT}` (after the current tool batch, before the next model
  call). A plain `prompt` while running is an error unless it carries
  `"streamingBehavior":"steer"`.
- Interrupt: `{"type":"abort"}`; the session stays loaded.
- End of turn: wait for `agent_settled` (not `agent_end`). Closing stdin shuts it down.
- Session: appended per message (`appendFileSync`); the file exists from the first user message.

**OMP** (`@oh-my-pi/pi-coding-agent@18.12.0`). pi's fork, same shape.
- Start: `omp --mode rpc --approval-mode yolo --model anthropic/M [--resume ID]`, with `PI_PROXY` set
  from `HTTPS_PROXY` as today.
- Commands: `prompt`, `steer`, `follow_up`, `abort`, and `abort_and_prompt` (interrupt and redirect
  in one call; useful later).
- Session: entries handed to the OS synchronously on append. To verify: how RPC mode reports the
  session id (pi uses `get_state`).

**OpenCode** (`opencode-ai@1.19.3`). **Proven end to end against a stand-in model.**
- In the adapter: start `opencode serve --port P --hostname 127.0.0.1` (inside the same container;
  localhost needs no egress). Wait until it answers.
- Session: `POST /session` returns its id before any prompt (write `HI_OUTPUT` at once), or reuse
  `HI_SESSION_ID` to continue.
- Run the turn and stream the usual JSON events with
  `opencode run --attach http://127.0.0.1:P --dir "$HI_WORKSPACE" --format json -m M -s ID "$TASK"`.
- Steer: `POST /session/{id}/prompt_async?directory=WS` with
  `{"model":{"providerID","modelID"},"parts":[{"type":"text","text":TEXT}]}` → 204. The message is
  saved at once and drives the next model step of the same turn.
- Interrupt: `POST /session/{id}/abort` (verified: idle in 0.06 s, server alive, context kept).
- End: `run --attach` exits when the session is idle; then stop `serve`.
- Kill durability: SQLite, written per message (verified: after a kill during a tool, the resumed
  model saw the partial turn with the tool marked interrupted).

**Kilo Code** (`@kilocode/cli@7.8.12`). An OpenCode fork; same adapter, `kilo serve`.
- Steer queues the message, then supersedes the running turn at the next step; the model sees the
  same history as with OpenCode (verified).
- `abort` takes `?scope=session|tree` (default `tree` also stops subagents).
- Signal the native binary, not the npm wrapper (`@kilocode/cli-linux-x64/bin/kilo`).

### 4.3 Tier A, with a caveat: one at a time, after the six

| Harness (pinned) | Steerable mode | Steer | Interrupt | Resolve first |
|---|---|---|---|---|
| MiMo Code (`@mimo-ai/cli@0.1.15`) | `mimo serve`, as OpenCode | `prompt_async` (verified) | `/abort` (verified) | Never use its ACP mode: a mid-turn prompt is silently dropped. A disconnected HTTP client cancels the turn. 20 steers a minute at most. |
| MiniMax Code (`@minimax-ai/code@0.6.12`) | `mcode acp` | `mcode/session/steer {sessionId, text}` | `session/cancel` | the method's exact wire name (with or without a leading `_`) |
| Gajae Code (`gajae-code@0.18.12`) | `gjc --mode acp` | `_gjc/sdk/control {sessionId, operation: "turn.steer", input: {text}}` | `session/cancel` | it starts a helper broker process; check it works and is cleaned up in the sandbox. Nothing is saved before the first reply. |
| J-Code (latest via installer) | `jcode api-bridge --stdio` | `soft_interrupt {session_id, content, urgent}` | `cancel` | it starts a background daemon that outlives the bridge; the adapter must stop it |
| Goose (latest via installer) | `goose acp` | `_goose/unstable/session/steer {sessionId, prompt, expectedRunId}` (run id from `session/update` `_meta.goose.activeRunId`) | `session/cancel` | the method is marked unstable |
| Hermes (`hermes-agent==0.19.0`) | `hermes acp` | a `session/prompt` whose text is `/steer TEXT` | `session/cancel` | the image installs `hermes-agent[anthropic]`; it needs the `[acp]` extra |
| Kimi Code (latest via installer) | `kimi web --no-open` (local REST) | `POST /api/v1/sessions/{id}/prompts`, then `…/prompts/{promptId}:steer` | `…/prompts/{promptId}:abort` | the installer now ships 2.2.0, a rewrite; check the current harness still works at all first |
| Qwen Code (`@qwen-code/qwen-code@0.25.2`) | `qwen --acp` | the adapter answers the CLI's `craft/drainMidTurnQueue` callback with the queued steers | `session/cancel` | the callback contract; its stream-json mode only queues, so is tier B without this |
| nanobot (`nanobot-ai==0.3.5`) | `nanobot gateway` + WebSocket | a message to a busy session is added to the running turn | `/stop` | the message envelope and config |
| OpenSquilla (0.5.6) | `opensquilla gateway run` + WebSocket JSON-RPC | `sessions.steer.v2` | `sessions.abort` | gateway auth; very few users |
| Grok CLI (latest via installer) | `grok agent --always-approve stdio` (ACP) | `x.ai/interject` (probably `_x.ai/interject` on the wire) | `session/cancel` | the method's name and parameters |

### 4.4 Tier B: interruptible, not steerable

Graceful cancel, then continue. `run.interactive: true` (for the interrupt line only); `steer`
returns 400, and clients use the recipe in §3.6.

| Harness | Graceful stop | Notes |
|---|---|---|
| Cline (`cline@3.0.73`) | ACP `session/cancel` (verified) | keep driving `cline --acp`, keep stdin open. Never send a second `session/prompt` mid-turn: it queues, and then cancel no longer works (verified). Nothing is saved before the first reply. |
| DeepSeek Harness (`@deepseek-ai/dsh@0.2.0-rc.2`) | `--profile acp`, `session/cancel` | a second prompt is rejected while one runs |
| OpenHands (`openhands==1.16.0`) | `openhands acp`, `session/cancel` (stops at the next step) | mid-turn prompts over ACP are racy; don't use them. Every event is saved as its own file, so resume is reliable. |
| Aider (`aider-chat==0.86.2`) | its stdin chat session (no `--message`), one SIGINT to the aider process | lines typed during a turn only queue. Two SIGINTs within 2 s exit. |
| CheetahClaws (`cheetahclaws==3.5.89`) | one SIGINT mid-turn, in its stdin chat session (as today) | saves its named session only on `/exit`; a hard kill loses the turn |

### 4.5 Tier C: neither

- **harness-engineering**: our own `harness.py`. Cancel ends the turn. Because we own it, it could
  become tier A later: between tool calls, read any control lines waiting on stdin.

### 4.6 For every harness, now: keep the session when a turn is cut short

Independent of steering, and needs no contract or server change. Each `report.py` (or adapter)
writes `HI_OUTPUT` atomically **as soon as it sees the session id**, not only at the end. Where the
CLI prints the id late, fix it in the folder:

| Harness | Where the id comes from early |
|---|---|
| Claude Code, Qwen Code | `system`/`init`, or choose it with `--session-id` |
| Codex | `thread.started`, the first event |
| pi, OMP, Gajae | the `session` header, the first line |
| DeepSeek Harness | the `session` event, before the task runs |
| OpenCode, Kilo, MiMo | the first `step_start`; in serve mode, `POST /session` |
| Grok CLI | pass `--session-id <new uuid>` on a first turn (today the id appears only at the end) |
| J-Code | switch `run --json` to `run --ndjson`: its first event is `start` with the id |
| Goose | name the session up front with `-n NAME` and resume with `-r -n NAME` |
| nanobot, OpenSquilla, Aider, harness-engineering | `run.sh` already knows the id (minted, chosen or constant): write it before starting |
| Hermes, Kimi Code | only printed at the end: after a kill, recover it with `-c` / `session list` |
| CheetahClaws, OpenHands | only on exit; accept, or recover from the CLI's own store |

---

## 5. Order of work

Each phase is one pull request (or a few), with tests, docs and a `CHANGELOG.md` section.

**Phase 0: the decision (owner).** Approve the contract amendment: reword `VISION.md` principle 2
and `AGENTS.md` principle 3 to say the contract was extended once with `run.interactive` and the
stdin control lines, and is closed again. Human tier: the owner merges it.

**Phase 1: keep the session when a turn is cut short** (harness folders only; patch release). §4.6
for every shipped harness, with atomic writes. Test: a fake harness that writes its session id and
is then killed; the record has the id, and the next turn gets it as `HI_SESSION_ID`.

**Phase 2: the core** (minor release, e.g. 1.1.0). §3.1 to §3.5.
- Tests go in the lowest layer that proves each promise:
  - `tests/test_harness.py`: an interactive harness gets a one-line request on an open stdin; a
    non-interactive one still gets today's input, closed; a steer before start is delivered after
    the request line, in order; steer on a non-interactive harness is `Invalid`; steer after the
    end is `Conflict`; an interrupt ends as `cancelled` with the reported session id, even on exit
    0; a harness that ignores the interrupt is killed after the grace.
  - `tests/test_platform.py`: steers are on the record and published to followers; `cancel(wait)`
    returns the final record; continuing a cancelled turn passes its session id.
  - `tests/test_api.py`: the endpoints and errors in §3.4; `harness.steer` in SSE order.
  - `tests/test_cli.py`: `hi steer`, `hi cancel --continue`.
- Add `tests/steer/`, a stand-in steerable harness (Python, standard library): it reports a session
  id at once, then "works" in steps (prints a line, sleeps briefly), checks stdin between steps,
  prints `{"steered": TEXT}` when a steer arrives, and on interrupt writes `HI_OUTPUT` and exits. A
  flag in its request metadata makes it ignore interrupts, to test the grace.
- `tests/fakes/docker` already passes stdin through (`os.execvp`); confirm with a Docker-runtime test.

**Phase 3: the six ready harnesses** (§4.2), plus MiMo (verified). Each with `adapter.py` and the
shared `hi_control.py`. Add `scripts/live_steer.py` beside `scripts/live_matrix.py`, run by hand
with real keys:
- Steer: ask for a slow task ("count from 1 to 30, one number per line into count.txt, running
  `sleep 1` between numbers"), wait for 5 numbers, steer "stop counting and write DONE to done.txt";
  pass if `done.txt` exists and `count.txt` stops early.
- Cancel and continue: same task, graceful cancel after 5 numbers; continue with "what were you
  doing, and how far did you get?"; pass if the answer names the counting and a number.

**Phase 4: the caveat harnesses** (§4.3), one pull request each, after resolving its caveat.

**Phase 5: tier B graceful stops** (§4.4).

**Phase 6: the users of it.**
- `hi run` as an interactive session (§3.5).
- The software factory (`mrcloudchase/software-factory-template`, `.factory/loop.py`): keep the
  tick running in a loop; while an agent turn runs, poll for the owner's new comments and forward
  them with the §3.6 recipe. A GitHub Actions job lasts at most 6 hours, so the loop re-dispatches
  itself before then, or runs on a host that stays up.
- Keeper (`.keeper/engine/runtime.py`) the same way, if wanted.

---

## 6. What must stay true

- No harness-specific code outside `harnesses/`. The server learns only "a turn can take input
  lines" and "an interrupt is a request, then a kill after a grace".
- A key never reaches a command line, a record, a log or an API response. Steer text is user input,
  stored on the record like the task.
- One turn per conversation: a steer goes to the running turn; it never starts a second one.
- A record is never left `running`: a graceful stop that hangs is killed after the grace.
- Non-interactive harnesses behave exactly as today.
- The library stays standard-library only (layers 0 to 6).

## 7. Risks

- **CLIs change their protocols.** Codex's app-server and Goose's steer method are marked
  experimental or unstable. Pin versions; the live steer check catches breakage; an adapter can
  fall back to tier B (interrupt only) by setting nothing else.
- **"Safe point" means after the current tool calls.** A long-running command is not cut short by
  a steer. Only Gajae (by default) and J-Code (with `urgent`) abort running tools; OMP can steer
  into a streaming reply, but only on OpenAI's Responses API.
- **A steer can race the end of the turn.** The harness should run a late steer as a continuation
  in the same process where its CLI allows (Claude Code does this itself); otherwise the server
  answers 409 and the client continues (§3.6).
- **Some modes start extra processes** (OpenCode-family `serve`, Gajae's broker, J-Code's daemon).
  The adapter owns them: start them, stop them, and never leave them behind. The container is
  removed at the end of the turn anyway.
- **A size budget.** `keeper.toml` caps the library near 2,000 lines. The server changes in §3 are
  small; the adapters live in harness folders and don't count.
