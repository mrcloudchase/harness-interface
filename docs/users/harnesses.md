# Use and write harnesses

A harness is any program you can start from a shell and hand a task to. To harness-interface, a
harness is a folder:
- a `harness.json` that says how the program runs;
- the scripts it runs.

The server has no code for any harness. Everything specific to a CLI lives in its folder.

## Use the shipped harnesses

Twenty-three ship with harness-interface, and the default sandbox has all their CLIs installed.

```bash
hi harness add --builtin                     # all of them
hi harness add --builtin claude-code codex   # or the ones you name
hi harness ls
```

Each one names the provider it expects ([providers](providers.md)). To run one:

```bash
hi run claude-code "Fix the failing test" -f prices.py -f test_prices.py -i "Keep changes minimal"
hi run claude-code/claude-opus-5-5 "…"       # pick the CLI's model
hi run claude-code "Now add a test for it" -c
```

The flags:
- `-f` puts a file in the workspace before the run.
- `-i` passes instructions; each harness puts them where its CLI reads them, such as `AGENTS.md`.
- `-c` continues the conversation.

The notes on each harness are in [harnesses/README.md](../../harnesses/README.md).

## Write your own

### The smallest harness

Two files in a folder named `hello`:

**`hello/harness.json`**

```json
{"name": "hello", "provider": "anthropic", "run": {"stdout": "text/plain"}}
```

**`hello/run.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "asked: $HI_TASK"                                       # stdout streams back as the output
echo "$HI_TASK" >> notes.txt                                 # a produced file, kept in the workspace
printf '{"status":"ok","session_id":"notes","answer":"%s notes so far"}' \
  "$(wc -l < notes.txt)" > "$HI_OUTPUT"                      # what the record reports
```

```bash
hi harness add ./hello
hi run hello "first"          # 1 notes so far
hi run hello "second" -c      # 2 notes so far: same workspace, same session
```

That is the whole idea:
- the task arrives as `HI_TASK`;
- whatever the harness prints streams back;
- files it writes in the workspace are kept;
- the JSON it writes to `HI_OUTPUT` becomes the record.

The full list of inputs and outputs is in the [harness contract](harness-contract.md).

### Wrap a real CLI

A real harness does five things.

**1. Map the provider onto the CLI's own settings.** The server gives every harness
`HI_PROVIDER_URL` and `HI_PROVIDER_KEY`; each CLI wants them under its own names:

```bash
export ANTHROPIC_BASE_URL="${HI_PROVIDER_URL%/}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY"
```

**2. Run the CLI headless, in one shot.** Use its non-interactive mode, with permission prompts
off. In Docker the sandbox is what limits it.

```bash
claude -p "$HI_TASK" --output-format stream-json --verbose --dangerously-skip-permissions \
  ${HI_MODEL:+--model "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} \
  | python3 "$HI_HARNESS_DIR/report.py"
```

**3. Report back.** Pipe the CLI's output through a small script that passes every line through
unchanged and picks out what the record needs. Then it writes that JSON to `HI_OUTPUT`:
- `answer`;
- `status`;
- `session_id`;
- `usage`;
- `cost_usd`.

Claude Code's reporter is twenty lines:

```python
import json, os, sys

out = {}
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "system" and ev.get("session_id"):
        out["session_id"] = ev["session_id"]
    if ev.get("type") == "result":
        out["status"] = "fail" if ev.get("is_error") else "ok"
        out["usage"] = ev.get("usage")
        out["cost_usd"] = ev.get("total_cost_usd")
        out["answer"] = ev.get("result") or ""
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
```

A CLI with no JSON mode gets a reporter that picks the answer out of its text, and its
`harness.json` declares `"stdout": "text/plain"`.

**4. Resume.** The `session_id` you report comes back as `HI_SESSION_ID` on the next turn. The
shipped harnesses use four patterns:

| Pattern | Example | How |
|---|---|---|
| The CLI's own session id | Claude Code, OpenCode, Hermes | report the id the CLI prints, pass it back with its resume flag |
| The latest session in `$HOME` | Codex, Aider | on a follow-up, resume the CLI's most recent session; the reported id only marks that there is one |
| A resume protocol | Cline | drive the CLI's Agent Client Protocol mode, and load the saved session |
| A transcript | harness-engineering | keep the conversation in `$HOME`, and hand the earlier turns back as context |

Keep the CLI's own state in the workspace's `.home` directory: set `"HOME": "{workspace}/.home"`
in `run.env`. It then survives between turns, and is never counted as a produced file.

**5. Take the instructions.** A request's `instructions` are its role for the harness. Write them
where the CLI reads them, with `files` in `harness.json`; they are written before every turn:

```json
"files": {"AGENTS.md": "{instructions}"}
```

Most CLIs read `AGENTS.md` from their working directory. Check the one you wrap, and check that
its model follows it: some read a name of their own (`CLAUDE.md`, `QWEN.md`), some read another
folder, some read it only once told to, and some read no file at all, or treat it as background
only. For those, the run script hands the instructions over with a flag, or puts them ahead of
the task. The shipped harnesses have an example of each
([notes](../../harnesses/README.md#notes-worth-knowing)).

### Develop it

- **Iterate locally.** Develop against the local runtime, `HI_RUNTIME=local hi server start`, so
  the harness runs as a plain process you can watch. It needs the CLI installed on your machine.
- **When a run fails,** `hi log <id>` shows the harness's stderr and `hi output <id>` its stdout.
- **Then use Docker.** Switch to the Docker runtime for the real thing. If your CLI isn't in the
  default image, add a sandbox that installs it ([sandboxes](sandboxes.md)), and name that sandbox
  in `harness.json`.
- **Re-add after changes.** After each change, `hi harness add ./your-harness` again. There's no
  restart; the next run uses the new version.

The 23 shipped harnesses in [harnesses/](../../harnesses/) are working examples of every pattern
above.
