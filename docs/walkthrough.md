# Walkthrough

From nothing to a resumed session, with the real commands.

## What it is

harness-interface is a small server that treats coding agents as infrastructure. You register a
harness, meaning any CLI you can run from a shell, as a YAML resource. You send it tasks over HTTP.
The agent's own output streams back unchanged, and the server records what happened: status, cost,
files produced, and a handle to resume the conversation later. When a request does not name a
harness, a routing rule you wrote picks one, optionally by asking TypeSafe's Jev model.

The server knows nothing about Claude Code, Codex or DeepSeek Harness. Each is a folder with three
files. Adding a fourth harness never changes the server.

## Deploy and set up

The server runs on one machine, next to the agent CLIs it will launch. Install those first, then
the server:

```bash
npm install -g @anthropic-ai/claude-code @openai/codex @deepseek-ai/dsh
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
uv pip install -e .        # or: pip install -e .
hi serve                   # http://127.0.0.1:8000, state under ./data (HI_DATA_DIR to move it)
```

Keep it on localhost. The box is the trust boundary: every harness runs with its approvals off,
and secrets go into each harness process's environment. A harness process also inherits the
server's environment, so start `hi serve` with the environment you want every harness to see.

In a second shell, store the provider keys. Each command reads the value from an environment
variable of the same name, or from stdin if you paste it:

```bash
hi secret ANTHROPIC_API_KEY
hi secret OPENAI_API_KEY
hi secret DEEPSEEK_API_KEY
hi secret TYPESAFE_API_KEY     # only needed for the Jev route
```

They land as mode-600 files under `data/secrets/`, which git ignores.

## Add harnesses

The server starts with zero harnesses. Register the ones you want:

```bash
hi apply harnesses/claude-code/harness.yaml harnesses/codex/harness.yaml harnesses/deepseek-harness/harness.yaml
```

Each apply validates the YAML, runs the resource's `check` command (for Claude Code,
`claude --version`), stores it with a version number, and prints whether the check passed.
`hi get /harnesses` lists what is registered; `hi apply` again bumps the version.

A harness folder holds three things:

| File | What it is |
|---|---|
| `harness.yaml` | the command, the env it needs, which secrets to inject, what files to write into the workspace first, and the `description` the router reads |
| `run.sh` | the command itself, and where every quirk of that CLI lives: Claude Code needs `IS_SANDBOX=1` as root, Codex needs `CODEX_HOME` created and the key logged in |
| `report.py` | passes the CLI's lines through to stdout and writes the three things the server reads back to `HI_OUTPUT`: `session_id`, `status`, `usage` |

To add a harness that does not exist yet, copy a folder, change those three files, and apply.
The process contract the server guarantees is in the README. In short: the request arrives on
stdin and in `HI_TASK`, `HI_MODEL`, `HI_SESSION_ID`; stdout is the response; the workspace diff
is the produced files.

## Create a routing rule

A request that names a harness goes there. A request that names none is decided by the one route
you have applied. Start simple:

```bash
hi apply routes/static.yaml        # everything unpinned goes to claude-code
```

When you have a Jev key, switch to the decision model:

```bash
hi apply routes/jev.yaml
```

That file is the routing rule, written in Jev's three question types. A `choice` question with
`criteria: from_registry` turns every registered harness into an option, described by the
`description` field from its YAML, so the description is the routing prompt. A `noul` asks
whether the task is risky. A `score` sizes it. Then a `decide` table reads the answers top to
bottom:

```yaml
decide:
  - when: risky.probability > 0.8
    then: reject needs a person before an agent acts
  - when: harness.confidence >= 0.6
    then: use harness.choice
  - then: use default
default: claude-code
```

Edit the questions or the threshold and re-apply; the server stores a new version. Set the
threshold from your own run history (every routed run records Jev's answers next to the outcome),
not by feel.

## Make a request

Send a task, a harness, files, and a check command that decides whether it was done right:

```bash
hi run "The tests are failing. Find out why and fix it." \
  --harness claude-code \
  --instructions "Keep changes minimal. Do not edit test files." \
  --file prices.py --file test_prices.py \
  --check "python3 -m unittest -q"
```

The first line on stderr says what was created: `run=r_… session=s_… harness=claude-code`.
Then stdout is Claude Code's own stream-json, exactly as the CLI printed it, until the process
exits. When it ends, the run record is printed to stderr. Leave off `--harness` and the route
decides instead.

The same request over HTTP:

```bash
curl -N http://127.0.0.1:8000/runs -H 'content-type: application/json' -d '{
  "task": "The tests are failing. Find out why and fix it.",
  "instructions": "Keep changes minimal. Do not edit test files.",
  "harness": "claude-code",
  "files": [{"name": "prices.py", "content": "..."}, {"name": "test_prices.py", "content": "..."}],
  "check": "python3 -m unittest -q"
}'
```

The response headers carry `X-Run-Id`, `X-Session-Id` and `X-Harness`, and the body streams.
Send `"stream": false` to get `{"run": …, "body": …}` as one JSON object instead.

## Review a response

The run record is the summary:

```bash
hi get /runs/r_55ac987ffe49
```

It holds the status, the exit code, the latency, the usage the harness reported, the files the
agent changed, the result of your `check`, the `verdict`, and, for a routed request, the decision:
which harness was chosen, Jev's confidence, the runner-up, which rule fired, and every raw answer.
Four more endpoints go deeper:

- `GET /runs/{id}/output` is the harness's stdout, exactly as it was streamed.
- `GET /runs/{id}/log` is the harness's stderr, which is where a CLI explains a failure.
- `GET /runs/{id}/files/prices.py` returns a produced file.
- `GET /sessions/{id}` shows the workspace path and the resume handle.

The verdict is the run's one label. With a `check`, the check decides. Without one, the route's
judge asks Jev whether the output accomplished the task, reading the task, the answer and the
produced files, so a "summarize this paper" task is labeled without a test suite. Disagree with
either, and `hi verdict <run> pass|fail --note "..."` records yours instead. `hi get /cards` shows
what those labels add up to per harness, which is what Jev reads when it routes.

`hi get /runs` lists every run. That list is the dataset: harness, task, check pass or fail,
cost, latency, and routing decision per row.

## Continue work, or start new work

A session is a workspace directory plus the harness's own conversation id. To continue, name it:

```bash
hi run "Now add a count() function and say what you changed earlier." --session s_8f7a00e13b3b
```

The router is skipped, the same directory is reused with the files as the agent left them, and
the CLI is relaunched with its resume flag, so it remembers the earlier conversation. A session is
pinned to the harness that created it for exactly this reason.

To start new work, leave `--session` off. You get a fresh workspace and, if you did not pin a
harness, a fresh routing decision. Attach files again if the new task needs them; nothing carries
over between sessions.

That is the whole loop: apply resources, send tasks, read records, continue or start fresh.
