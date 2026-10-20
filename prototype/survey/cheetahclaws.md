# CheetahClaws — cheetahclaws 3.5.89 (pin: cheetahclaws==3.5.89)

**Verdict:** works with caveats. It runs only as a REPL fed on stdin, with output for a terminal (ANSI, spinner frames, hard-wrapped boxes). The gpt-5 family fails through `custom/` unless `max_tokens` is 0 in its config. Usage is 0 on OpenAI.
**Tier:** steered. Its REPL catches SIGINT per turn and keeps the history, so the adapter SIGINTs the running turn and writes the new text as the next line (adapter.py prototype, gpt-5-mini). After 3 numbers: done.txt=DONE, count stayed 3, and the run exited on its own.

## Inputs
- Task: one line on stdin per turn. `cheetahclaws --accept-all -m <model>` with stdin piped never shows the setup wizard (that needs a TTY). A positional prompt or `-p` runs one query and returns with no way to resume, so the REPL is the only route. Slash lines (`/resume`, `/save`, `/cost`, `/exit`) are REPL commands.
- **Multi-line tasks break.** Each `\n` starts a new turn. The bracketed-paste markers `ESC[200~…ESC[201~` keep only the first line, because select() misses input already in Python's buffer. Tested: 3 extra lines became 3 separate inputs. Send the task as one line (join its lines).
- Approval: `--accept-all` (auto mode is already the default). **`AskUserQuestion` reads stdin with input() mid-turn** and so consumed queued lines (APPLE/BANANA/CHERRY were taken as answers). Disable it with `"disabled_tools":["AskUserQuestion"]` in config.json, or it can also eat `/exit` or a steer.
- Model: `-m provider/name` (`custom/x`, `openai/x`, `anthropic/x`, `deepseek/x`, …). A bare name is auto-detected by prefix; the fallback is openai. Working dir = cwd (no flag; `/cwd` exists).
- Instructions: `CLAUDE.md` in the cwd and its parents, plus `~/.claude/CLAUDE.md`, re-read every turn. The model follows it: with "end every reply with PINEAPPLE", gpt-5-mini replied "OK PINEAPPLE" and later "…ORCHID. PINEAPPLE". It reads no AGENTS.md.

## Provider
- API shapes: OpenAI chat completions (openai SDK) and Anthropic Messages (anthropic SDK). Ollama and litellm also exist (not tested).
- `custom/<name>`: `CUSTOM_BASE_URL` (WITH `/v1`, e.g. `https://api.openai.com/v1`) and `CUSTOM_API_KEY`. Config `custom_base_url` overrides the env var. **It sends `max_tokens` (default 40000)**, which gpt-5-mini rejects with 400 "Unsupported parameter: 'max_tokens'… Use 'max_completion_tokens'". Only the built-in `openai` provider sends `max_completion_tokens`. Fix: write `{"config_version":2,"max_tokens":0}` to `~/.cheetahclaws/config.json` so no cap is sent (verified working). DeepSeek `custom/deepseek-chat` works with the defaults.
- `openai/<name>`: `OPENAI_API_KEY`, base URL hard-coded to api.openai.com (no env override). That suits OpenAI only.
- Anthropic: `ANTHROPIC_API_KEY` plus **`ANTHROPIC_ENDPOINT`** (base WITHOUT `/v1`; the SDK adds it), model `claude-sonnet-4-6` or `anthropic/…`. Tested OK. It sends prompt-cache `cache_control`.
- No login. Key never persisted (checked: no key in any file under HOME or the workspace). HTTPS_PROXY is honored (every call was a CONNECT on my logging proxy). Startup traffic goes only to the provider host: `custom/` also GETs `<base>/models` for the context size. No telemetry or update checks seen. Set `CHEETAH_SUGGEST=0`: in a TTY it otherwise makes an extra "predict next prompt" LLM call after each turn. Turn the per-turn LLM call off whenever prompt_toolkit is importable.

## Artifacts it loads
All paths are under `$HOME/.cheetahclaws/` (no env override except HOME):
- `config.json` (DEFAULTS in config.py: `max_tokens`, `disabled_tools`, `tool_profile`, `permission_mode`, `custom_base_url`, budgets, `resume_replay`…).
- `skills/<name>.md` or `skills/<name>/SKILL.md`; the project's `<cwd>/.cheetahclaws/skills` takes priority.
- `mcp.json` (`{"mcpServers":{…}}`, Claude Code format); a project `.mcp.json` in the cwd or its parents overrides it.
- `plugins/` + `plugins.json` (or `<cwd>/.cheetahclaws/plugins*`), and `memory/*.md` (or `<cwd>/.cheetahclaws/memory`).
- `~/.claude/CLAUDE.md` (global instructions). No hooks system found. Skills, MCP and plugins were not tested live.

## Outputs
- Text only, made for a terminal: ANSI colours, spinner frames joined with `\r`, Rich boxes hard-wrapped at 80 columns. A turn opens with `╭─ CheetahClaws ●` and ends with `╰────`. An interrupted turn prints `(interrupted)` and no `╰`. Tool calls show as summaries ("Ran 1 shell command") inside the box. The startup banner is also a `╭─ CheetahClaws v3.5.89` box, so match the `●`.
- Errors go into the box as `[Failed — <Error>: …]` plus JSON log lines (`{"level":"error","event":"api_call_error",…}`) in the same stream. **The exit code is 0 even when every API call fails.**
- Usage: footer `✻ Worked for 4s · ↓ 44` (output only). `/cost` prints `Input tokens / Output tokens / Cache read / Est. cost: $X`, cumulative for the session including resumed totals. The session JSON has `total_input_tokens`/`total_output_tokens`. OpenAI (`custom/` and `openai/`) always reports 0, because it never asks for `stream_options.include_usage`. DeepSeek and Anthropic report real numbers (DeepSeek: 18,007 in / 44 out, $0.0052).
- Resume id: printed only at save time (`/exit` → `… session_HHMMSS_<id>.json  (id: <id>)`), with a NEW id on every save. `/save <abs path>` saves to a path you choose, which gives a handle known up front.

## State it keeps
- `$HOME/.cheetahclaws/sessions/{mr_sessions/session_latest.json (autosaved after every turn), daily/<date>/session_*.json, history.json}`, `sessions.db` (SQLite), `quota/<date>.json`, `input_history*.txt`, `memory/`.
- `$HOME/.nano_claude/checkpoints/<sid>/` holds snapshots and file backups.
- **In the workspace:** `.nano_claude/plans/<id>.md` when the model uses EnterPlanMode (sonnet did, unprompted). The project scope of MemorySave writes `.cheetahclaws/memory/`. Disable `EnterPlanMode`/`ExitPlanMode` via `disabled_tools`, or exclude those dirs from the diff.
- The model also uses MemorySave on its own ("remember ORCHID" → `~/.cheetahclaws/memory/remember_word_orchid.md`), which carries facts across sessions in the same HOME.

## Continue
`/resume <id>` (searches session_latest, daily/ and the DB), `/resume <abs path.json>`, or `/resume last`. It then replays the transcript to stdout (outside any ● box) and continues. Proven: run 1 "Remember the word ORCHID. Reply OK." → `(id: f6b5052b)`. Then I deleted `~/.cheetahclaws/memory` so memory couldn't answer. Run 2 `/resume f6b5052b` + "Which word…?" → "You asked me to remember the word ORCHID." Also proven through adapter.py with `/save`/`/resume` on `$HOME/.cheetahclaws/sessions/hi/<rid>.json`.

## Mid-turn steering
- No steer, queue or RPC protocol. `serve`/daemon `session.send` only publishes an event; the web UI was not explored.
- Text typed while it works is **queued**, not acted on mid-turn. Steer sent after 3 numbers (gpt-5-mini): counting went to 30, then the steer ran as the next turn (done.txt written at 177 s).
- **SIGINT + next line works as steering.** A KeyboardInterrupt in a turn is caught by the REPL ("(interrupted)"), history is kept (`sanitize_history` repairs half-done tool calls), and the next stdin line starts a new turn in the same process. Tested raw with claude-sonnet-4-6: SIGINT at count 3, then the steer → done.txt=DONE, count 3, exit 0 at +4 s.
- Caveat: the Bash tool runs each command with `start_new_session=True`, so SIGINT misses it and an in-flight command keeps running. gpt-5-mini ran a loop in one command and the count went on to 26 after the interrupt. adapter.py therefore also SIGTERMs the process group of every child of cheetahclaws. With that: count 3, done.txt=DONE (pass).
- Rules for the adapter: send only ONE SIGINT per turn (3 within 2 s → `os._exit(1)`), and only while a turn runs. A SIGINT at the idle prompt saves and exits; one during startup is untested.

## Graceful stop
- No abort command of its own. SIGINT mid-turn → "(interrupted)" in under 0.1 s, then the next stdin line runs. Feed `/exit` (or close stdin), which saves and exits 0 (raw REPL: 0.7 s after SIGINT). SIGINT or EOF at the prompt → saves and exits 0.
- Resumed after the SIGINT (sonnet, raw REPL): "I was writing numbers 1–30 to count.txt … got through 3 numbers (1, 2, 3)". Through adapter.py (gpt-5-mini): "…running shell commands that write the numbers 1–30… executed two commands so far" (the in-flight 3rd was not recorded). Pass.

## Worst case
Not needed. If the saved file is missing (e.g. SIGKILL), `session_latest.json` holds every completed turn (autosaved after each one), so `/resume last` (or its path) recovers.

## The folder we should ship
- harness.json: provider `openai`; `run.interrupt: "steered"`; env `HOME={workspace}/.home`, `CHEETAH_PT_INPUT=0`, `CHEETAH_SUGGEST=0`; files `CLAUDE.md: {instructions}` plus `.home/.cheetahclaws/config.json: {"config_version":2,"max_tokens":0,"disabled_tools":["AskUserQuestion","EnterPlanMode","ExitPlanMode"]}` (or have run.sh write it); stdout `text/plain`.
- run.sh: artifacts loop as today; `mkdir -p $HOME`; `export CUSTOM_BASE_URL="${HI_PROVIDER_URL%/}" CUSTOM_API_KEY="$HI_PROVIDER_KEY"`; `exec python3 "$HI_HARNESS_DIR/adapter.py"`. For an `anthropic` provider variant: `ANTHROPIC_ENDPOINT`/`ANTHROPIC_API_KEY` and `-m anthropic/$HI_MODEL`.
- adapter.py (prototype: `work/cheetahclaws/folder/adapter.py`, 103 lines):
  - Writes `{"resume": <new rid>}` to HI_OUTPUT before starting, then runs `cheetahclaws --accept-all -m custom/$HI_MODEL` (new session).
  - Sends `/resume $HOME/.cheetahclaws/sessions/hi/$HI_RESUME.json` if set, then HI_TASK joined into one line.
  - Tracks turns from `╭─ CheetahClaws ●` / `╰─` / interrupts. Each later stdin JSON line → if a turn is running: SIGINT once plus SIGTERM to the tool process groups; then the text as a line.
  - When no turn is queued, or on EOF or SIGINT: `/save …/hi/<rid>.json` + `/exit`.
- report.py (fold into adapter.py): answer = the last assistant text in the saved session JSON (exact, unwrapped). status = fail on rc≠0, a missing save, or `[Failed —` in the last box; it should also say "interrupted" when the stop hit a running turn (the prototype says "ok"). usage = delta of `total_*_tokens` against the resumed file; cost from `/cost` deltas (`Est. cost: $`), and 0/unknown on OpenAI. Write resume early (done).
- artifacts: skills → `.cheetahclaws/skills/<n>/SKILL.md`, MCP → `.cheetahclaws/mcp.json`, global rules → `.claude/CLAUDE.md`, settings → `.cheetahclaws/config.json` (merge with the required keys).
- changes from today's folder:
  - The default `gpt-4.1-mini` works around the max_tokens bug only by luck: any gpt-5/o-series HI_MODEL gets a 400 and still exits 0. Add `max_tokens:0`.
  - A multi-line HI_TASK becomes several turns.
  - AskUserQuestion can swallow `/exit` (then the run waits for EOF); disable it.
  - It uses `HI_SESSION_ID`/`session_id`, not `HI_RESUME`/`resume`. The id appears only at exit; use `/save <path>` for an early handle.
  - report.py's box regex also matches the startup banner box. The answer it takes includes "Ran N shell command" summaries and 80-column hard wraps.
  - There is no usage (`/cost` would give it for non-OpenAI providers), and status is "ok" even on API failure (exit 0).

## Evidence
(Work dir: `work/cheetahclaws/`. Logs in `logs/`; drivers `bin/drive.py` for the raw REPL and `bin/drive_adapter.py` for the adapter. Logging CONNECT proxy `bin/logproxy.py`.)
- r1 `custom/gpt-5-mini` with default config → 400 max_tokens, `[Failed — BadRequestError…]`, exit 0. Retried with `max_tokens:0`: "OK PINEAPPLE" (MemorySave called), `(id: f6b5052b)`, 17 s. CONNECTs: api.openai.com only.
- r2 `/resume f6b5052b` (memory dir deleted) → "ORCHID. PINEAPPLE", exit 0. `/cost` → 0 tokens, $0.
- r3 queue test (gpt-5-mini): steer typed at count 3 (38.7 s) → count reached 30, steer ran as the next turn, done.txt at ~177 s, exit 0 at 199 s.
- r4 sonnet via ANTHROPIC_ENDPOINT: SIGINT at count 3 (24.4 s) → "(interrupted)", `/exit` saved, exit 0 at 25.1 s, count 3. r5 `/resume 024d9198` → "…got through 3 numbers (1, 2, 3)". `/cost`: in 13, out 972, cache read 11,799, $0.0182.
- r6 raw steer (sonnet): SIGINT at 3, then the steer line → done.txt=DONE, count 3, exit 0 at 28.1 s.
- r7 bracketed-paste 4-line task → read as 1 line; AskUserQuestion consumed the other 3 lines as answers.
- a8 adapter + gpt-5-mini: run 1 had a banner-box bug (fixed). Run 2 without the tool kill: interrupted at 3, done.txt, but the orphan loop carried count to 26. Run 3 with the tool kill: count 3, done.txt=DONE, adapter exited by itself at 83.8 s with stdin still open; early HI_OUTPUT `{"resume":"089e35e9849f","status":"running"}` at 1.5 s.
- a9 adapter, SIGINT to its group at count 3 → cheetahclaws "(interrupted)", `/save` + `/exit`, adapter exit 0 in about 0.2 s, count 3. a10 `HI_RESUME=4fadc6fc9dad` → names the counting and "two commands so far".
- r11 `custom/deepseek-chat` with defaults: tool call OK. `/cost` 18,007 in / 44 out / $0.0052. CONNECTs: api.deepseek.com ×3 only.
- Key scan of the whole work dir (HOME and workspaces) for all three keys: no hits.
