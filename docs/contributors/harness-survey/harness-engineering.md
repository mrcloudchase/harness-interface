# Harness-engineering — harness.py (repo 597699f) on anthropic SDK 1.15.0, Python 3.13 (pin: none; the image runs an unpinned `pip3 install anthropic`)

**Verdict:** works with caveats. Headless, Anthropic Messages only, and it reaches only the provider host. Today's folder streams nothing until exit, ignores HI_MODEL, and loses the whole turn on SIGINT.
**Tier:** steered, after a ~90-line change to harness.py (prototype `work/harness-engineering/folder/`): a steer sent at n=3 gave done.txt=DONE with the count at 3. SIGINT and end of stdin exit 130 in 0.3 s with the session saved, and a resumed run names "3". Unchanged, it is `responded`.

## Inputs
- Task: the argv joined (`python3 harness.py "<task>"`). With no argv it is an interactive `< ` prompt loop on stdin. A one-off request breaks after the first reply that has no tool call. It never asks for approval because it has no permission system; the system prompt only says "if it can't be undone, ask first".
- Model: hardcoded `MODEL = "claude-sonnet-5-5"`, with no flag and no env var, so HI_MODEL is ignored today. max_tokens is 16384, with no thinking and no streaming.
- Working dir: the cwd. Every command runs from there via `subprocess.run(cmd, shell=True, executable=$SHELL or /bin/sh)`, with **no timeout** and with **stdin inherited** (today a command can read the request body the server wrote to stdin).
- Instruction file: none. It does not read AGENTS.md or CLAUDE.md (tested: a workspace AGENTS.md rule "end with MANGO" was ignored). run.sh prepends `request.instructions` to the task, and the model follows it ("end with PINEAPPLE" → it did).
- System prompt: a fixed "Mind" text plus harness.py's own source (`mechanics()`), cache_control ephemeral, about 3.45k tokens.

## Provider
- Shape: Anthropic Messages only (`client.messages.create`). DeepSeek `https://api.deepseek.com/anthropic` works: it made a tool call and answered, and it accepts the hardcoded model name.
- Env: `ANTHROPIC_API_KEY` (x-api-key) or `ANTHROPIC_AUTH_TOKEN` (Bearer), and `ANTHROPIC_BASE_URL`. Optional: `ANTHROPIC_CUSTOM_HEADERS`. The base URL must NOT include `/v1`: `.../v1` → 404 NotFoundError, while a trailing `/` is fine. With no key in the env, SDK 1.15 falls back to `ANTHROPIC_PROFILE`, federation env vars, or a profile under its config dir.
- There is no login step and no persistence: no file under HOME or the workspace contained either key (grep after all runs).
- HTTPS_PROXY: honored (httpx2, trust_env). A dead proxy gave APIConnectionError, exit 1. Through a logging CONNECT proxy the only host was `api.anthropic.com:443`; there is no catalog, update check or telemetry. The SDK carries the OpenTelemetry API only (no exporter); `ANTHROPIC_OPEN_TELEMETRY=false` disables it.
- Retries: the SDK default (2) on 429, 5xx and connection errors.

## Artifacts it loads
- Nothing: no settings, skills, MCP, hooks or rules. The `artifacts` file mechanism in run.sh works, but harness.py reads nothing under $HOME. Users could only drop files the model might find via the shell (unprompted, it won't look).

## Outputs
- Plain text on stdout: `> ` model text (continuation lines indented 2), `$ <cmd>`, `  └ <output>` (or `(exit N)`). Errors are a Python traceback on stderr (run.sh merges it with 2>&1).
- **Buffering:** print() without flush, so to a pipe everything appears only at exit. Tested: every line showed up at t=18.3 s when the process died. Fix: `python3 -u` or `PYTHONUNBUFFERED=1`.
- Answer: the last `> ` block (report.py). Usage: not printed today; `response.usage` exists per call. Cost: none (there is no price table). Resume id: none, since it holds no session.
- Exit codes: 0 when done; 1 on API errors (401 bad key, 404 /v1 URL, connection error); -2 (killed by SIGINT, KeyboardInterrupt traceback) on Ctrl-C; "can't be summarized" exits 1 with the message on stderr.

## State it keeps
- Nothing: the conversation lives in memory. It writes nothing to HOME or the workspace beyond what its commands do. Today's report.py appends `$HOME/conversation.txt` (`< task` / `> answer`) at the end of a turn.

## Continue
- harness.py itself: none. Today's folder fakes it: report.py writes `session_id:"conversation"`, and on a follow-up run.sh prepends `[the earlier conversation]` + conversation.txt to the task. ORCHID via today's run.sh: run 1 "OK. I'll remember the word ORCHID.", run 2 "The word was **ORCHID**." (answers only; tool calls and results are lost).
- Prototype (real resume): `HARNESS_SESSION=<id>` loads `$HOME/.harness/sessions/<id>.json`, the full message list, rewritten atomically after every append. It prints `[session <id>]` before the first model call, at about 1.0 s. ORCHID via the prototype folder (HI_RESUME=id): run 2 "The word you asked me to remember is **ORCHID**." An unknown id silently starts a new session.

## Mid-turn steering
- None today: argv mode never reads stdin.
- Prototype (`--steer`): a daemon thread reads stdin lines, each one a JSON string, and queues them. After each batch of tool results, queued text is appended to that same user message as `{"type":"text","text":"[<ts>] [added while you worked] <text>"}`, so it lands before the next model call. Text queued after a final answer is added and the loop continues. Commands get `stdin=DEVNULL` so they can't eat steer lines. End of stdin → `os.kill(self, SIGINT)` = graceful stop.
- Test through the prototype folder, sonnet-4-6: the steer went in at 10.3 s (n=3) while the next call was in flight. That call's `sleep 1` ran, the steer was delivered with its result at 12.6 s, `echo DONE > done.txt` ran at 13.9 s, and it exited 0 at 16.0 s. count=3, done.txt=DONE. Pass. On an earlier run the in-flight command was `sleep 1 && echo 4`, so the count stopped at 4. Pass.

## Graceful stop
- It has no abort message of its own; Ctrl-C is the only stop.
- Original, killpg SIGINT at n=3 (sonnet-5-5): rc -2 after 0.30 s, with a KeyboardInterrupt traceback from inside `subprocess.run`. Nothing was saved. Through today's run.sh, report.py also dies from SIGINT, so there is no output.json, no conversation.txt, and stdout is lost (buffered). The follow-up "what were you doing?" answered "I have no memory of earlier work". **Fail.**
- Prototype: `except KeyboardInterrupt` around the loop fills `(interrupted)` tool_results for unfinished tool_use blocks, adds "[the person interrupted you here]", saves, prints `[interrupted]` and `[usage {...}]`, and exits 130. report.py ignores SIGINT and writes output.json (resume, usage, answer). Through the folder: SIGINT exited 130 in 0.30 s with count=3, and so did end of stdin (mid-`sleep`, 0.30 s; subprocess's 0.25 s SIGINT grace). The resumed run said "I got through **3 numbers**". Pass. SIGINT during an API call was not separately tested (no assistant message is appended, so the saved state stays valid).

## Worst case
- Today's transcript hand-back (answers only, written at turn end) carries finished turns but nothing from an interrupted one. If the prototype is not adopted, at least make report.py ignore SIGINT and append `< task` + whatever `> ` blocks it saw.

## The folder we should ship
- harness.json: provider `anthropic`; `run.env` `HOME={workspace}/.home`; `run.stdout` `text/plain`; `run.interrupt` `steered`; timeout 900. No `files`.
- run.sh: (prototype `folder/run.sh`) runs artifacts as today, then `IFS= read -r _request` (line 1; the request must be ONE line, but today's server body is `indent=2` JSON). Exports `ANTHROPIC_BASE_URL=${HI_PROVIDER_URL%/}`, `ANTHROPIC_API_KEY=$HI_PROVIDER_KEY`, `HARNESS_MODEL=$HI_MODEL`, `HARNESS_SESSION=${HI_RESUME:-$HI_SESSION_ID}`, and builds the task from instructions + task (no transcript). Then `python3 -u harness.py --steer "$task" 2>&1 | python3 report.py`. With `--steer`, end of stdin stops the run, so do NOT pass it when the server closes stdin right after the request (today's non-interactive mode).
- report.py: `signal(SIGINT, SIG_IGN)`. Passes lines through, flushed. On `[session <id>]` (line 1) it writes `{"resume","session_id"}` to HI_OUTPUT at once. Usage comes from `[usage {...}]` (input/output/cache_* tokens summed over calls). Answer = last `> ` block. status `fail` if a `Traceback` or the can't-summarize line appears, else `ok`. No cost.
- harness.py changes (diff: `work/harness-engineering/harness.py.diff`):
  1. `MODEL = os.environ.get("HARNESS_MODEL") or "claude-sonnet-5-5"`.
  2. `stdin=subprocess.DEVNULL` on the tool's subprocess.run.
  3. `SESSION`/`SAVED` + `load()`/`save()`: `$HOME/.harness/sessions/<id>.json`, assistant content stored as `b.model_dump(exclude_none=True)`. It was re-sent fine, including the new `caller` field. `print("[session id]")` first.
  4. `say()` joins the person's text to a trailing user message, so resumes and steers never put two user turns in a row.
  5. `--steer`: a stdin-reader thread + queue, drained after each tool batch; EOF → SIGINT. Start the thread inside the try, or an early EOF gives a raw traceback (seen once).
  6. `try/except KeyboardInterrupt` in control_flow: close dangling tool_use, save, exit 130. handle_output fills a list the caller owns, so finished commands survive.
  7. Sum `response.usage` in request_response and print `[usage {...}]` in a `finally`.
  Optional: a per-command timeout.
- artifacts: nothing it would load; keep the empty template.
- changes from today's folder: HI_MODEL is ignored; there is no `-u`/PYTHONUNBUFFERED (nothing streams); report.py dies on SIGINT (no output.json); no status or usage; key `session_id` (the brief's `resume` is missing; write both); the transcript loses tool work and interrupted turns; tool commands inherit the request on stdin; the description still says "Reports no usage".

## Evidence
- Scripts are in `work/harness-engineering/`: `drive.py` (start_new_session; it watches count.txt, and at n=3 sends a steer line, SIGINT, or EOF), `frun.sh` (fakes the server's HI_* env plus `.hi/request.json` and runs a folder's run.sh), `env.py` (fresh HOME, stripped CLAUDE*/CCR*/ANTHROPIC*/OPENAI*/NO_PROXY/PYTHONUNBUFFERED).
- Original "Reply with just OK." → `> OK`, rc 0, 3.3 s. Bogus key → 401, rc 1. BASE_URL `/v1` → 404, rc 1. HTTPS_PROXY=127.0.0.1:9 → APIConnectionError, rc 1. DeepSeek → `$ echo hi-from-shell` then answered, rc 0.
- Original counting + SIGINT at n=3 (18.3 s): rc -2, 0.30 s; stdout arrived all at once at exit; HOME empty. Today's run.sh + SIGINT: rc -2 (bash), no output.json, no transcript. The follow-up did not know the work.
- Today's run.sh ORCHID: OK / "The word was **ORCHID**." Instructions → PINEAPPLE ending followed; AGENTS.md (MANGO) ignored.
- Prototype folder (sonnet-4-6): steer → count 3, DONE, rc 0 (16.0 s); SIGINT → rc 130, 0.30 s, output.json with resume + usage; EOF → rc 130, 0.30 s. Resume after SIGINT → "got through 3 numbers". ORCHID with HI_RESUME → "ORCHID".
- Logging proxy: a single `CONNECT api.anthropic.com:443`. Key grep over the work dir (excluding venv): 0 files.
