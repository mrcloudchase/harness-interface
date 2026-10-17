# Walkthrough

From nothing to a settled contest and a resumed session, with the real commands.

## What it is

harness-interface is a small server that treats coding agents as contestants. You register a
harness, meaning any CLI you can run from a shell, as a YAML resource. You send tasks over HTTP.
By default every registered harness gets the task at once, TypeSafe's Jev model judges each
output and picks a winner, and the cards keep score: runs, delivered, failed, contests, won,
lost. The agents' own output streams back unchanged, and the server records what happened:
status, cost, files produced, and a handle to resume the winner's conversation later. A request
can instead name one harness, or ask the route to pick one from the records.

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
hi secret TYPESAFE_API_KEY     # the judge, the referee, and the Jev route
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
| `harness.yaml` | the command, the env it needs, which secrets to inject, what files to write into the workspace first, and a `description` for people |
| `run.sh` | the command itself, and where every quirk of that CLI lives: Claude Code needs `IS_SANDBOX=1` as root, Codex needs `CODEX_HOME` created and the key logged in |
| `report.py` | passes the CLI's lines through to stdout and writes what the server reads back to `HI_OUTPUT`: `session_id`, `status`, `usage`, `answer` |

To add a harness that does not exist yet, copy a folder, change those three files, and apply.
The process contract the server guarantees is in the README. In short: the request arrives on
stdin and in `HI_TASK`, `HI_MODEL`, `HI_SESSION_ID`; stdout is the response; the workspace diff
is the produced files.

## Apply the policy

One Route resource holds the policy: how every run is judged, how a contest is won, and how
`route` mode picks a harness. Apply the one that ships:

```bash
hi apply routes/jev.yaml
```

Its `judge` is a single question Jev answers about every finished run, reading the task, the
instructions, the harness's answer and the files it produced: was the task completed? The
`success_when` threshold turns that into the run's verdict. Its `arena` is the question the
referee asks when several harnesses delivered: which output best accomplishes the task?

The rest is `route` mode, written in Jev's three question types. A `choice` question with
`criteria: from_registry` turns every registered harness into an option, and that option is the
harness's name and its record, such as `12 runs: 9 delivered, 3 failed (75%). 4 contests: 3 won,
1 lost.` Jev never sees the descriptions. A `noul` asks whether the task is risky. A `score` sizes
it. Then a `decide` table reads the answers top to bottom:

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
not by feel. A routed run gets a verdict like any other but never a win or a loss: those come only
from contests, so the route cannot feed the harness it favors.

## Make a request

Send a task, instructions and files. With nothing else, it is a fan-out: every registered harness
runs it at once.

```bash
hi run "The tests are failing. Find out why and fix it." \
  --instructions "Keep changes minimal. Do not edit test files." \
  --file prices.py --file test_prices.py
```

The first line on stderr says what was created: `contest=c_…`. Then stdout is NDJSON, one line
per line of output from whichever harness printed it, `{"harness": "codex", "line": "…"}`, until
every entrant has finished. The last line is the settled contest. When it ends, the contest record
is printed to stderr: the winner, the winner's session, and the run id of each entrant.

Add `--mode route` and the route picks one harness from the records. Add `--harness claude-code`
and that harness runs. Either way the first line on stderr is `run=r_… session=s_… harness=…`,
stdout is that CLI's own output exactly as it printed it, and the run record follows on stderr.

The same fan-out over HTTP:

```bash
curl -N http://127.0.0.1:8000/runs -H 'content-type: application/json' -d '{
  "task": "The tests are failing. Find out why and fix it.",
  "instructions": "Keep changes minimal. Do not edit test files.",
  "files": [{"name": "prices.py", "content": "..."}, {"name": "test_prices.py", "content": "..."}]
}'
```

The response carries `X-Contest-Id` and the body streams. Send `"stream": false` to get
`{"contest": …, "runs": {…}}` as one JSON object instead. A `route` or `named` request (add
`"mode": "route"`, or `"harness": "claude-code"`) carries `X-Run-Id`, `X-Session-Id` and
`X-Harness`, streams the harness's own output, and answers `{"run": …, "body": …}` unstreamed.

## Review a response

The contest record is the summary of a fan-out:

```bash
hi get /contests/c_2f9a1c0b7e44
```

It names the entrants and their run ids, the winner, how it was settled (the only one to deliver,
or the referee's choice with a probability per entrant), and the winner's session. Each entrant's
run record is the summary of what that harness did:

```bash
hi get /runs/r_55ac987ffe49
```

It holds the status, the exit code, the latency, the usage the harness reported, the files the
agent changed, the `verdict`, and, for a routed request, the decision: which harness was chosen,
Jev's confidence, the runner-up, which rule fired, and every raw answer. Four more endpoints go
deeper:

- `GET /runs/{id}/output` is the harness's stdout, exactly as it was streamed.
- `GET /runs/{id}/log` is the harness's stderr, which is where a CLI explains a failure.
- `GET /runs/{id}/files/prices.py` returns a produced file.
- `GET /sessions/{id}` shows the workspace path and the resume handle.

The verdict is the run's one label: did it deliver. A harness that failed, timed out or was
cancelled is a failure by status. Otherwise the judge asks Jev, reading the task, the answer and
the produced files, so a "summarize this paper" task is labeled without a test suite. Jev cannot
run code or check facts; when you know better, `hi verdict <run> pass|fail --note "..."` records
yours instead. `hi get /cards` shows what the labels and the contests add up to per harness, and
the record sentence there is exactly what Jev reads when it routes.

`hi get /runs` lists every run and `hi get /contests` every contest. Together they are the
dataset: for every task, which harnesses delivered, which one won, at what cost and latency.

## Continue work, or start new work

A session is a workspace directory plus the harness's own conversation id. A contest leaves one
session per entrant and names the winner's; to continue, name a session:

```bash
hi run "Now add a count() function and say what you changed earlier." --session s_8f7a00e13b3b
```

No fan-out and no routing: the same directory is reused with the files as the agent left them,
and that CLI is relaunched with its resume flag, so it remembers the earlier conversation. A
session is pinned to the harness that created it for exactly this reason.

To start new work, leave `--session` off. You get a fresh contest, or a fresh routing decision
with `--mode route`. Attach files again if the new task needs them; nothing carries over between
sessions.

That is the whole loop: apply resources, send tasks, read the contest, continue the winner or
start fresh.

## The same loop in a browser

Everything above is also at `http://127.0.0.1:8000/ui`. **New run** has the form with the mode
selector; a fan-out streams every harness side by side and ends with the contest, a single run
streams that harness's output. **Contests** lists every contest and opens into the entrants, their
verdicts and the referee's probabilities. **Runs** lists every run and opens into the decision as
bars, the verdict with pass and fail buttons, the answer, usage, output and log, and a "continue
this session" button. **Sessions** groups runs by session. **Harnesses** shows the cards with their
records and applies a pasted YAML. **Route** edits the policy and previews a routing decision for a
sample task, showing the exact Jev request. **Secrets** stores values by name.
