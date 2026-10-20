# Aider — aider 0.86.2 (pin: aider-chat==0.86.2)

**Verdict:** works with caveats. It is a file editor, not a shell agent: `--yes-always` never runs its suggested shell commands, it exits 0 even on API errors and on SIGINT, and it has no JSON output.
**Tier:** steered. An adapter drives interactive aider over piped stdin (`--no-fancy-input`). A steer SIGINTs the reply in flight, then sends the text: done.txt was written and n01–n05 were never applied. The fallback is `continued` via `--restore-chat-history`, which is proven.

## Inputs
- Task: `--message TEXT` (`-m`) or `--message-file FILE` (not tested); runs one turn, then exits. Without either it runs interactively and reads stdin. With non-tty stdin plus `--no-fancy-input`, it uses plain `input()`: one line = one message, and `{TAG` … `TAG}` wraps multi-line text. EOF makes it exit cleanly. From source: text starting with `/` runs an aider command (`/run`, `/add`…) in both modes.
- Never asks: `--yes-always`. It auto-answers every confirm with yes, except `explicit_yes_required` ones (shell commands), which get **no**. It auto-adds files the task mentions (a.py was added and edited without `--file`).
- Model: `--model provider/name`. Working dir = cwd. Git root is auto-detected (`--no-git` turns it off).
- Instruction file: none. A workspace AGENTS.md was ignored (no KIWI). With `--read AGENTS.md` it was followed (the reply ended with KIWI). `.aider.conf.yml` `read:` is equivalent.
- Every flag also has an `AIDER_<FLAG>` env var.

## Provider
- Uses litellm, so every shape is available. Tested OK:
  - Anthropic Messages: `anthropic/<m>`, `ANTHROPIC_API_KEY`, `ANTHROPIC_API_BASE` (or `ANTHROPIC_BASE_URL`). The URL must **not** include `/v1`, because litellm appends `/v1/messages`; with `/v1` the result is NotFoundError. DeepSeek at `https://api.deepseek.com/anthropic` works.
  - OpenAI chat completions: `openai/<m>`, `OPENAI_API_KEY`, `OPENAI_API_BASE` **with** `/v1`. Tested gpt-5-mini on api.openai.com and deepseek-chat on api.deepseek.com/v1.
  - OpenAI Responses: not tested.
- Always prefix the provider: a bare `deepseek-chat` would go to litellm's deepseek route.
- No login step. But with no key and no `--model`, it starts an **OpenRouter OAuth flow** (callback on localhost:8484) and waits 5 minutes. Always pass both.
- It honors `HTTPS_PROXY` (every CONNECT went through a logging proxy).
- Startup fetches, unmitigated:
  - `pypi.org` (update check): `--no-check-update`.
  - `raw.githubusercontent.com` ×2. One is litellm's price map (`LITELLM_LOCAL_MODEL_COST_MAP=True`). The other is aider's own `~/.aider/caches/model_prices_and_context_window.json`. That one is refetched whenever the file is missing, empty (`{}`) or >24h old, and a failure is printed to stdout, so write a fresh non-empty file each run (today's trick works).
  - Analytics: no posthog call was seen. `--analytics-disable` writes `~/.aider/analytics.json` and prints one line.
  - Fully mitigated, only the provider host is contacted.
- Key persistence: none found. All homes, logs and workspaces were scanned for all 3 keys: 0 hits. The command line is logged to the chat history; `--anthropic-api-key`/`--openai-api-key` are scrubbed there, `--api-key P=K` is not, so pass keys by env.
- Caution: `.env` files in $HOME, the git root and cwd are loaded with `override=True`, so a workspace `.env` can override the provider env.

## Artifacts it loads
- `.aider.conf.yml`: cwd, git root, $HOME (later wins per configargparse; `-c` overrides).
- `.env`: $HOME, git root, cwd, plus `--env-file`; also `~/.aider/oauth-keys.env`.
- `.aider.model.settings.yml` and `.aider.model.metadata.json`: $HOME, git root, cwd. These are the fix for models aider doesn't know (edit format, context window, prices).
- `.aiderignore` (git root); `--load FILE` (a file of /commands run at start).
- No skills, MCP, hooks or custom commands exist.

## Outputs
- Text only (`--no-pretty`; `--stream` prints progressively). The answer is the reply text; with the `whole` format it includes file listings. Then:
  - `Tokens: 2.3k sent[, N cache hit|write], 459 received[. Cost: $0.0015 message, $0.0015 session.]`
  - `Applied edit to X` per file.
- Cost appears only when litellm knows the model. `claude-sonnet-4-6` is not in the bundled map: no cost, and aider falls back to the `whole` edit format with the warning "Unknown context window".
- Errors print as `litellm.AuthenticationError: …` / `litellm.NotFoundError: …`, with no Tokens line.
- **Exit code is 0** on success, on API errors, and on SIGINT during the LLM call. A SIGINT during startup imports gives a KeyboardInterrupt traceback and death by SIGINT.
- No session id exists; the history file is the state, so the handle is whatever the harness chooses (known before start).

## State it keeps
- `--chat-history-file` (markdown transcript; this is what restore reads), `--input-history-file`, `--llm-history-file` (full prompts). Their defaults are `.aider.*` in the **git root or cwd** (the workspace!); point them at $HOME.
- `~/.aider/` holds `caches/`, `installs.json` and `analytics.json`.
- Workspace side effects:
  - With git and the repo map on: `.aider.tags.cache.v4/` in the repo root (none with `--map-tokens 0`).
  - New files it creates are **`git add`ed** (staged) even with `--no-auto-commits`.
  - It adds `.aider*` to `.gitignore` unless `--no-gitignore`.
  - Without a git identity it prints an "Update git name" nag.

## Continue
- `--restore-chat-history` with the same `--chat-history-file`: it parses the md back into messages (and summarizes if over `--max-chat-history-tokens`).
- Proven: run 1 "Remember the word ORCHID. Reply OK." → `OK`. Run 2 with restore → "The word you asked me to remember was **ORCHID**." Control run without restore → `UNKNOWN`.
- It restores only what was printed (user lines, replies, tool lines), not in-memory interrupt markers.

## Mid-turn steering
- There is no RPC/JSON/ACP mode. One "turn" is one LLM reply, plus up to 3 reflections (mentioned files, lint/test). It cannot run shell, so the literal counting task can't run. Tested as written: it wrote `count.sh` with 30 echo/sleep lines, ran nothing, produced no count.txt, and exited 0 in 8 s.
- Adapted test: "Create thirty new files n01.txt…n30.txt, each containing its number, one file listing each, in order", with interactive aider `--no-fancy-input --stream`.
  - When stdout showed `n03.txt`, the adapter sent SIGINT (aider in its own session) and aider printed `^C again to exit` and its `> ` prompt.
  - The adapter then wrote "Stop counting now. Instead write the word DONE into done.txt and finish."
  - Result: done.txt = DONE. Files present: only done.txt (n01–n05 had streamed but were never applied). The adapter closed stdin when idle; aider exited 0. 8 s total. **Pass.**
- Semantics:
  - An interrupt drops **all** edits of the reply in flight. Its partial text goes to the chat history; "^C KeyboardInterrupt / I see that you interrupted" is kept in memory only.
  - The alternative is to queue the steer until the `> ` prompt (no loss, but no early stop).
  - Busy/idle is known only from stdout ending in `> ` (or `diff> ` when `--edit-format` differs from the model default). That is a heuristic.
  - Without `--no-fancy-input`, prompt_toolkit stays on: it prints "Warning: Input is not a terminal" and redraws the prompt with `\r` padding, which breaks idle detection.
- Python scripting API (`Coder.create(...).run(msg)`): not tested. It could replace prompt sniffing but needs aider's venv python.

## Graceful stop
- No abort message of its own; Ctrl-C is the abort.
- Headless `--message --stream`, SIGINT to the pgid at `n03.txt`: exit **0** after 0.6 s, no files written, no Tokens line, and the partial reply was saved to the chat history.
  - Resumed with the question "what were you doing before, and how far did you get?", it answered: "I was creating 30 text files (n01.txt through n30.txt)… I got through n01.txt… and n02.txt… before being interrupted." **Pass**: it names the task and a number. It overstates progress, since nothing was applied.
- `--no-stream`, SIGINT at 6 s: exit 0 after 0.7 s; the history holds only the user line (a resume would know the task, not the progress).
- A second SIGINT within 2 s calls `sys.exit()`.
- Through the adapter, SIGINT was forwarded to aider, then EOF: aider exited 0 1.3 s later.

## Worst case
Not needed: the history md under $HOME already carries the conversation. If it is lost, hand the earlier transcript back with `--read <file>` or prepend it to the message.

## The folder we should ship
- harness.json:
  - provider `anthropic`, `run.interrupt: "steered"`, stdout `text/plain`, files `AGENTS.md: {instructions}`.
  - env: `HOME={workspace}/.home`, `LITELLM_LOCAL_MODEL_COST_MAP=True`, `AIDER_CHECK_UPDATE=false`.
- run.sh:
  - Install the artifacts as today.
  - `id=${HI_RESUME:-$(uuid)}`. Model: `*/*` as given, else `anthropic/`.
  - URL: `anthropic/*` uses `ANTHROPIC_API_BASE=${URL%/}` (strip a trailing `/v1`); `openai/*` uses `OPENAI_API_BASE` (ensure `/v1`). Key goes in the matching `*_API_KEY`.
  - Refresh the price-cache file. `exec python3 adapter.py`.
  - adapter.py starts `aider --model M [--read AGENTS.md] --yes-always --no-pretty --no-fancy-input --stream --no-auto-commits --no-dirty-commits --no-gitignore --no-show-model-warnings --no-check-update --no-show-release-notes --analytics-disable --chat-history-file $HOME/.aider/s/$id.md --input-history-file … --llm-history-file … [--restore-chat-history if HI_RESUME]` with a stdin pipe, in its own session.
  - It writes the task as `{HI\n…\nHI}`.
  - On each later stdin line (a JSON string): if busy, SIGINT aider, wait for `> `, then send it as `{HI…HI}`.
  - When idle with nothing queued, or on stdin EOF or SIGINT (forward SIGINT, then close), it closes aider's stdin.
  - A prototype is at `work/aider/bin/adapter.py`.
- report.py:
  - Write `{"resume": id}` to `$HI_OUTPUT` at start.
  - answer = the last reply's text, minus echo, noise, `^C again to exit` and `Applied edit` lines.
  - usage = the sum over `Tokens:` lines; cost_usd = the last `Cost: … $Y session`.
  - status: `fail` on a `litellm.*Error` line; `interrupted` when the last message has no Tokens line after `^C`; otherwise `ok`. The exit code is useless.
- artifacts: `.aider.conf.yml`, `.aider.model.settings.yml` and `.aider.model.metadata.json` go to `$HOME`. Conventions files go to `$HOME/…` and are read via `read:` in the conf. `.env` should not be used for keys.
- changes from today's folder:
  - Uses `HI_SESSION_ID` / `"session_id"`, not `HI_RESUME` / `"resume"`, and doesn't write early. It has no `run.interrupt`.
  - It is Anthropic-only (no `openai/` route) and doesn't strip `/v1`.
  - Models unknown to aider (e.g. `claude-sonnet-4-6`) silently get the `whole` format and no cost. Add `--edit-format diff` or ship model settings/metadata.
  - `git config user.name/email` is written into the user's `.git/config`; use `$HOME/.gitconfig` (`--global`; not tested whether that silences the nag).
  - Add `--no-fancy-input` and `</dev/null` in headless mode.
  - report.py marks an interrupt as `fail` and leaves `^C again to exit` and the git-nag lines in the answer.
  - New files get staged (git add); mention it, or run `git reset` on aider's adds.

## Evidence
(Logs are in `work/aider/logs/`; the runners are in `work/aider/bin/`.)
- `base1`, no mitigations: CONNECTs to pypi.org, raw.githubusercontent.com ×2 and api.anthropic.com; 16.6 s (first-run imports ~11 s); release-notes prompt auto-answered `y`. `base2`, with the env/flags but no price cache: raw.githubusercontent.com + the provider. The `cont*` runs, with the cache file: provider only.
- `cont1/2/3`: ORCHID → `OK`, then `**ORCHID**` with restore, `UNKNOWN` without; exit 0, ~5 s each.
- `ins1/ins2`: AGENTS.md ignored without `--read`; `KIWI` with it.
- `countA`, the literal counting task: wrote `count.sh`, no shell run, exit 0.
- `steer3`, adapter: steer at 4.3 s after n05 streamed; SIGINT → `^C again to exit` → `> `; done.txt applied at 5.6 s; files: done.txt only; exit 0 at 8.0 s. `steer1/2` (fancy input) put `\r`-padded prompts on stdout and broke idle detection.
- `stop1`, `--message --stream`, SIGINT at `n03.txt`: exit 0 in 0.6 s, 0 files. `stop1r` restore: names the 30-file task and n02.
- `stop2`, SIGINT at 1 s (imports): traceback, rc −2. `stop3`, `--no-stream`, SIGINT at 6 s: exit 0 in 0.7 s. `steer4`, SIGINT to the adapter: aider exit 0 1.3 s later.
- `oa` openai/gpt-5-mini: `Tokens: 2.3k sent, 459 received. Cost: $0.0015`. `ds` anthropic/deepseek-chat via `/anthropic` and `dso` openai/deepseek-chat via `/v1`: PONG, no cost.
- `bad1` (invalid key): AuthenticationError, rc 0. `bad2` (base with `/v1`): NotFoundError, rc 0.
- `git1` (git, `--map-tokens 0`): edited a.py (mentioned, auto-added) and created b.py, which was staged (`AM`); no commit, no tags cache.
- Keys: 0 occurrences in any file written. The homes and workspaces were deleted afterwards.
