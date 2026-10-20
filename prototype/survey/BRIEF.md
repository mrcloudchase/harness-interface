# Harness survey: the brief every surveyor follows

## Why

harness-interface runs coding CLIs ("harnesses") in a sandbox behind one API. A harness is a folder:
`harness.json` (provider, sandbox, templated `files`, `run.env`, `run.stdout` content type), `run.sh`
(maps the request onto the CLI's own flags and runs it headless), `report.py` (passes the CLI's output
through unchanged, flushed, and writes `{"answer","status","resume","usage","cost_usd"}` to the file at
`$HI_OUTPUT`) and `artifacts` (files from the folder copied under `$HOME` before each run: skills,
settings, MCP config, hooks). The server knows nothing about any CLI. The contract is minimal and
generic, like a terminal: env vars in (`HI_TASK`, `HI_MODEL`, `HI_RESUME`, `HI_PROVIDER_URL`,
`HI_PROVIDER_KEY`, `HI_WORKSPACE`, `HI_HARNESS_DIR`, `HI_OUTPUT`), the request JSON on stdin, stdout and
stderr out, workspace files changed, SIGINT to stop.

We are adding interactive sessions. Each harness declares `run.interrupt`:
- `steered`: the run keeps stdin open; line 1 is the request, each later line is one JSON string of new
  text from the user, and the folder (usually an `adapter.py`) hands it to the CLI **while it works**;
  SIGINT or end of stdin = the CLI's graceful stop.
- `continued`: on SIGINT the CLI stops gracefully and its conversation is saved, so the next run resumes
  it with the handle the harness reported (early, the moment it is known).
- `responded`: neither; the next run can only carry the earlier work in another way (a transcript handed
  back, files in the workspace).

Each run gets a fresh, locked-down container: no capabilities, read-only root, writable workspace and
`/tmp` only, `HOME` = `<workspace>/.home`, network only to the provider's host through an HTTPS CONNECT
proxy (`HTTPS_PROXY`), no DNS. The provider (url + key) is given per run as env vars; **nothing secret
may be baked into the image or written anywhere the server serves**. Providers should be swappable
across harnesses: a harness speaks one or more API shapes (Anthropic Messages, OpenAI Responses, OpenAI
chat completions) and any provider serving that shape should work.

You survey **one** harness and write what we need to build its folder well, and to choose its
`run.interrupt` tier, with evidence.

## Rules

- **Do not modify anything under `/home/user/harness-interface` or any git repository.** Read the
  current folder there (`harnesses/<name>/`) to compare. Work only in your own directory:
  `SCRATCH/harness-survey/work/<name>/`, where SCRATCH is
  `/tmp/claude-0/-home-user/37719b48-fc3a-58ba-bb72-5869c819d794/scratchpad`.
- **Secrets:** keys are in `/home/user/harness-interface/data/secrets/{ANTHROPIC_API_KEY,OPENAI_API_KEY,
  DEEPSEEK_API_KEY}`. Load one only into the environment of the process you start (read it in Python,
  or `VAR="$(cat FILE)"` inline). Never print, echo, log or write a key; never paste raw output that
  might hold one. If a CLI writes the key into its own files, say where (that matters) and delete them
  when you are done.
- **Environment:** start every CLI with a fresh `HOME` inside your work dir and a scratch workspace dir
  as its cwd, and strip inherited `CLAUDE*`, `CCR*`, `ANTHROPIC*`, `OPENAI*` and `HTTPS_PROXY`-unrelated
  agent variables from the child env (`CLAUDECODE` makes Claude Code refuse to start). Keep the
  machine's `HTTPS_PROXY`/CA settings, which the network needs.
- **Disk is tight (about 6 GB free, shared with 22 other surveyors).** The CLI is already installed on
  this machine (see your assignment). Use it. Only if its version differs from the pin AND the pinned
  one is a small npm/pip install, install the pin into your work dir (`npm i --prefix`, or
  `uv tool run`/a venv) and say which you tested. Delete caches you create; keep your dir under 300 MB.
- **Models:** for Anthropic use `claude-sonnet-4-6` (smaller models do all the counting in one shell
  command, so a steer can't land between numbers); for OpenAI `gpt-5-mini`; for DeepSeek
  `deepseek-chat`. Retry politely on 429.
- **Time:** aim to finish within about 40 minutes. Prefer `--help`, then docs/source (the installed
  package's files are on disk), then running it. Don't let one stuck experiment eat the time: use
  timeouts on everything.

## What to find out (and how)

1. **Inputs.** How the task is given (argument, stdin, file); non-interactive/headless flags; approval
   and permission flags (it must never stop to ask); model flag; working-dir flag; which instruction
   file it reads (`AGENTS.md`, `CLAUDE.md`, other) and whether its model actually follows it.
2. **Provider.** Which API shapes it speaks; the exact env vars or config for base URL and key; whether
   the URL wants `/v1` or not; whether it needs a login step; whether it fetches anything at startup
   from hosts other than the provider (model catalogs, update checks, telemetry) and how to turn that
   off; whether it honors `HTTPS_PROXY`. Where, if anywhere, it persists the key.
3. **Artifacts it loads.** Config/settings files, skills, MCP config, hooks, custom commands, rules:
   their paths under `$HOME` (or env overrides such as `CODEX_HOME`), and which are picked up from the
   workspace instead.
4. **Outputs.** Output formats (text, JSON, NDJSON events); the event types; where the final answer,
   usage, cost, status and its session/resume id appear, and **how early** the resume id appears;
   exit codes on success and failure.
5. **State.** Where it keeps sessions, transcripts, caches and logs; anything it writes into the
   working dir (which would show up as the user's changes).
6. **Continue.** How to resume a previous conversation in a new run (flag, id, "continue last"); prove
   it: run 1 "Remember the word ORCHID. Reply OK.", run 2 resumed "Which word did I ask you to
   remember?".
7. **Mid-turn steering.** Any way to give it more text while it works: a stream-json/RPC/ACP/server
   mode, a steer/queue message, an interject call. Find the exact protocol. **Test it** with the
   counting task below: after 3 numbers, send "Stop counting now. Instead write the word DONE into
   done.txt and finish." Pass = done.txt appears and counting stops well short of 30.
8. **Graceful stop.** Its own interrupt/abort message if it has one (test it), and SIGINT to its process
   group (`start_new_session=True`, then `os.killpg(pgid, SIGINT)`) in its plain headless mode: does it
   exit, how fast, with what code, is the conversation saved, and does a resumed run know "what were you
   doing before, and how far did you get?" (Pass = it names the counting and a number.)
9. **Worst case.** If it can't be resumed at all, how the next run could carry the earlier work in
   (a transcript file in `$HOME` handed back as context, as `harnesses/harness-engineering` does).

Counting task (use in a fresh workspace): "Using the shell, write the numbers 1 to 30 to count.txt, one
per line, running `sleep 1` between each number (one shell command per number). Do not write them all
at once."

## What to write

Write `SCRATCH/harness-survey/<name>.md`, **at most about 120 lines**, in exactly this shape:

```
# <Name> — <cli> <version tested> (pin: <pinned version>)

**Verdict:** works | works with caveats | doesn't work — one line why.
**Tier:** steered | continued | responded — one line of evidence.

## Inputs
## Provider
## Artifacts it loads
## Outputs
## State it keeps
## Continue
## Mid-turn steering
## Graceful stop
## Worst case
## The folder we should ship
- harness.json: (provider default, env, files, stdout type)
- run.sh: (the headless command; for steered, how adapter.py drives it)
- report.py: (where answer / status / resume / usage / cost come from; when to write early)
- artifacts: (what users would drop in, and where each goes)
- changes from today's folder: (what is wrong or missing in harnesses/<name>/ now)
## Evidence
(the commands and stdin messages you ran, and what happened: event types, numbers counted, exit
codes, timings — brief)
```

Be exact (flag names, env var names, message shapes) and terse. Say "not tested" or "unknown" where
true; never guess. Your final reply to whoever started you is only: the file's path, the Verdict line
and the Tier line.
