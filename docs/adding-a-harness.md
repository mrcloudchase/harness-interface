# Adding a harness

A harness is a folder with three files. Writing them is a matter of answering nine questions about
the CLI, then putting each answer in the file that owns it. This page walks the nine questions,
shows the answers for Claude Code, Codex and DeepSeek Harness side by side, and ends with how to
prove the result.

## The nine questions

Answer these by reading `cli --help`, then running the CLI once by hand in a scratch directory
with its machine-readable flag on, and looking at what it printed and what it wrote under `HOME`.

| # | Question | Why the server needs it |
|---|---|---|
| 1 | **Headless.** How do you hand it one task and have it exit? Prompt as an argument or on stdin? | `run.sh` is that one command |
| 2 | **Approvals.** How do you switch off interactive permission prompts? Nobody is there to answer. | without this the run hangs until the timeout |
| 3 | **Output.** Is there a JSON or NDJSON stream flag? What are the event types? | `report.py` reads it; clients receive it |
| 4 | **Auth.** How does the key get in: an env var, a config file, a login command? A base URL? | `secrets:` names the env var; `run.sh` does anything beyond that |
| 5 | **Model.** A flag, an env var, a config file, or fixed by a profile? | `run.sh` maps `HI_MODEL` onto it, or ignores it |
| 6 | **State.** Where does it write transcripts and sessions? | `env.HOME` points that inside the workspace so resume survives |
| 7 | **Resume.** What is the resume flag, and which event in the output carries the id? | `run.sh` uses `HI_SESSION_ID`; `report.py` reports `session_id` |
| 8 | **Instructions.** Which file does it read from the working directory? | `files:` writes the request's instructions there |
| 9 | **Usage, status and answer.** Which event carries token counts, which says the turn succeeded, and which carries the final text? | `report.py` reports `usage`, `status` and `answer` |

Then one open-ended question: what did the first hand run complain about? That is the quirk list.
Claude Code refuses to skip permissions as root unless `IS_SANDBOX=1` is set. Codex refuses to start
when `CODEX_HOME` does not exist and ignores `OPENAI_API_KEY` for its built-in provider. Every
quirk goes in `run.sh` or `env:`, never in the server.

## The answers, side by side

| # | claude-code | codex | deepseek-harness |
|---|---|---|---|
| 1 | `claude -p "<task>"` | `codex exec "<task>"` | `dsh --profile headless "<task>"` |
| 2 | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox --skip-git-repo-check` | none needed in headless |
| 3 | `--output-format stream-json --verbose`: `system`, `assistant`, `user`, `result` | `--json`: `thread.started`, `item.completed`, `turn.completed`, `turn.failed` | `--json`: `session`, `status`, `text`, `tool_call`, `tool_result`, `final` |
| 4 | `ANTHROPIC_API_KEY` env | `codex login --with-api-key` reading stdin, writes `$CODEX_HOME/auth.json` | `DEEPSEEK_API_KEY` env |
| 5 | `--model` | `-m` | fixed by the profile; `HI_MODEL` unused |
| 6 | `$HOME/.claude/projects/*.jsonl` | `$CODEX_HOME/sessions/` | `$HOME/.dsh/sessions/` |
| 7 | `--resume <id>`; id in `system/init` `session_id` | `exec resume --last`; id in `thread.started` `thread_id` | `--session-id <id>`; id in `session` `sessionId` |
| 8 | `AGENTS.md` (also reads `CLAUDE.md`) | `AGENTS.md` | `AGENTS.md` |
| 9 | `result`: `usage`, `is_error`, `total_cost_usd` | `turn.completed`: `usage`; `turn.failed` means fail | `status` `step_end`: `usage` per step, summed; `status` `turn_end` `reason.kind` |
| quirks | `IS_SANDBOX=1` as root | `mkdir -p "$CODEX_HOME"` first | `DSH_TELEMETRY_DISABLED=1` |

## Where each answer goes

### harness.yaml

Questions 4, 5, 6, 8 and the description. The description is not documentation: it is the text
the router hands to Jev as this harness's option, so write what it is good at, which models it
runs, and roughly what it costs.

```yaml
kind: Harness
name: codex
description: >
  OpenAI's Codex CLI, headless. A coding agent that edits files and runs commands in the
  workspace. Best for OpenAI models and GPT-family reasoning on code. Low to mid cost.
labels: [coding, shell, files, tests]
models: [gpt-5.3-codex, gpt-5.2-codex]        # question 5: what the model flag accepts
secrets: [OPENAI_API_KEY]                       # question 4: injected into the process env
files:
  AGENTS.md: "{request.instructions}"           # question 8
run:
  argv: [bash, "{harness_dir}/run.sh"]
  env:
    HOME: "{workspace}/.home"                   # question 6: state inside the workspace
    CODEX_HOME: "{workspace}/.home/.codex"
  stdout: application/x-ndjson                  # question 3: what clients receive
  timeout_s: 900
check: [codex, --version]                       # readiness probe at apply time
```

`{workspace}`, `{harness_dir}`, `{request.*}` and `{session.*}` are the template variables.

### run.sh

Questions 1, 2, 5, 7 and the quirks. It is a shell script because resume is conditional and
quirks are imperative. The server hands it `HI_TASK`, `HI_MODEL`, `HI_SESSION_ID`, `HI_OUTPUT`,
`HI_WORKSPACE`, `HI_HARNESS_DIR` and the declared secrets.

```bash
#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$CODEX_HOME"                                   # quirk
printenv OPENAI_API_KEY | codex login --with-api-key >/dev/null   # question 4, the part env cannot do
flags=(--json --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check)   # questions 3 and 2
[ -n "${HI_MODEL:-}" ] && flags+=(-m "$HI_MODEL")        # question 5
if [ -n "${HI_SESSION_ID:-}" ] && [ -d "$CODEX_HOME/sessions" ]; then
  codex exec resume --last "${flags[@]}" "$HI_TASK"      # question 7
else
  codex exec "${flags[@]}" --cd "$HI_WORKSPACE" "$HI_TASK"   # question 1
fi | python3 "$HI_HARNESS_DIR/report.py"
```

Claude Code's is one line because it has no quirks beyond an env var:

```bash
claude -p "$HI_TASK" --output-format stream-json --verbose --dangerously-skip-permissions \
  ${HI_MODEL:+--model "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} \
  | python3 "$HI_HARNESS_DIR/report.py"
```

DeepSeek Harness's is the same shape with `--session-id` and no model flag.

### report.py

Questions 7 and 9. It is a filter: every line in is written out unchanged, and at the end it writes
up to four fields to `HI_OUTPUT`. The three differ only in which event carries what:

| | claude-code | codex | deepseek-harness |
|---|---|---|---|
| `session_id` | `type == "system"` and `session_id` | `type == "thread.started"` and `thread_id` | `type == "session"` and `sessionId` |
| `usage` | `type == "result"`, `usage` | `type == "turn.completed"`, `usage` | sum of `usage` over `status` events with `phase == "step_end"` |
| `status` | `"fail"` if `is_error` else `"ok"` | `"ok"` on `turn.completed`, `"fail"` on `turn.failed` or `error` | `"ok"` if `turn_end` `reason.kind == "completed"` |
| `answer` | `result`, `result` | the last `agent_message` text | `final`, `text` |

Any of the fields may be left out. Without `answer` the judge reads the tail of stdout instead. Without `status` the exit code decides. Without
`session_id` a follow-up starts the CLI fresh in the same workspace, with the files but not the
conversation. Without `usage` the run has no cost.

A CLI with no JSON mode at all gets a two-line `run.sh` and no `report.py`: stdout is text, the
exit code is the status, and the resource's `stdout:` says `text/plain`.

## Prove it

```bash
hi apply harnesses/<name>/harness.yaml            # check_ok must be true
hi run "What files are here? One sentence." --harness <name> --file some.py
hi get /runs/<id>                                 # status ok, usage present
hi get /sessions/<session>                        # session_id present
hi run "What did I ask you before?" --session <session>   # the answer proves resume
```

If the second run does not remember the first, question 6 or 7 is wrong: either the CLI's state is
not under the `HOME` you set, or the resume flag or the id event is not what you thought. The run's
log (`/runs/<id>/log`) is the CLI's stderr and usually says which.
