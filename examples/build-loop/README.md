# A build loop

`loop.py` builds a project from a spec and an acceptance test suite by driving harnesses through
harness-interface. It runs unattended until every test passes, or until it runs out of time or
budget. You don't prompt the harness; the loop does, and the tests decide when it's done.

```
plan ─► for each task: build ─► verify ─► review ─► checkpoint
                         ▲        │ fail: the failures go back to the harness; after N tries,
                         └────────┘ roll back and escalate to the next harness
```

## What makes it robust

| What goes wrong in real loops | What this loop does |
|---|---|
| a harness says it's done when it isn't | the acceptance tests decide, run in a throwaway container with no network |
| a harness "fixes" the tests instead of the code | its edits to the tests are thrown away, and it's told so |
| a bad turn wrecks good work | each accepted task is a git commit; unaccepted work is rolled back |
| one harness gets stuck | after `--tries`, the task escalates to the next of `--workers` |
| code passes the tests but is wrong or messy | a different harness reviews each passing change; its objections get one round of revision, but the tests still decide, and an objection a change is accepted over is shown in the result |
| it runs forever | `--minutes` and `--budget`: at the deadline it cancels the run in flight, at the budget it starts no new turn, and either way it stops cleanly. The result says how many turns reported no cost, which the budget can't count. |
| it crashes halfway | state is saved after each task; run it again with the same `--repo` and it resumes |
| you can't see what happened | each harness's own output streams to the terminal as it works, each turn's diff is shown after it, and every turn is in `.loop/log.jsonl` |

## Run it

The demo project is [switchboard/](switchboard/): a spec for a small API server that runs harness
commands by name, records each run and continues it, plus 16 acceptance tests.

**1. The toolchain.** Give the harnesses a sandbox with the project's toolchain, so they can run
the tests themselves. Build the same image for the loop's own checks:

```dockerfile
# switchboard-dev.Dockerfile: the default sandbox, plus Python's test toolchain
FROM harness-interface/default:<tag>        # see: docker images 'harness-interface/default'
USER root
RUN pip3 install --no-cache-dir --break-system-packages fastapi httpx pytest uvicorn
USER agent
```

```bash
hi sandbox add switchboard-dev switchboard-dev.Dockerfile
docker build -t switchboard-check -f switchboard-dev.Dockerfile .
```

**2. The harnesses.** Point the workers at that sandbox. Set `"sandbox": "switchboard-dev"` in a
copy of each harness's `harness.json`, then add them:

```bash
hi harness add ./claude-code ./codex
```

**3. Run it.**

```bash
python loop.py --project switchboard --repo ./switchboard-build \
  --workers claude-code,codex --reviewers codex,claude-code \
  --minutes 20 --budget 15 --check-image switchboard-check
```

The built project ends up in `--repo`: a git repository with one commit per accepted task.
`hi show <id>`, `hi diff <id>` and `hi output <id>` replay any turn in `.loop/log.jsonl`.

## A real run

Given 20 minutes and a $15 budget, the loop built switchboard from its spec in 5 minutes. All 16
acceptance tests pass. Claude Code reported $1.21 for its turns; Codex reports tokens, not
dollars, so its four reviews aren't in that figure.

The plan had six tasks. Claude Code built two of them, and the tests for the other four already
passed by the time the loop reached them:

| Task | |
|---|---|
| 1. App structure and harness storage | Passed its tests on the first try. Codex asked for fractional timeouts, a refused trailing newline in names, and the list and delete endpoints; one revision, then approved. |
| 2. Harness retrieval and deletion | already passing: the revision of task 1 had added them |
| 3. Run execution | Passed every test on the first try. Codex caught a truthiness check that let an empty `previous_run_id` through; fixed. Its second review objected that the endpoint blocks the server while a command runs, and that a timeout's output can fail to decode. Both are real, and no test covers them; after the one revision round the change was accepted on its passing tests, with the objection shown in the result. |
| 4–6. Timeouts, recording runs, continuing them | already passing after task 3 |

Task 3 is the lesson: the reviewer found real bugs that no acceptance test covers. When that
happens, add a test for it, and the next run's tests decide it.

Watch it: [build-loop.gif](../../docs/media/build-loop.gif) at 6× speed, or the full recording
with `asciinema play docs/media/build-loop.cast`.

## Options

| | |
|---|---|
| `--project` | a folder with `SPEC.md` and `tests/` |
| `--repo` | where the loop keeps the project it builds |
| `--planner` | the harness that turns the spec into tasks (default `claude-code`) |
| `--workers` | the harnesses that build, in escalation order (default `claude-code,codex`) |
| `--reviewers` | the first of these that isn't the worker reviews (default `codex,claude-code`) |
| `--tries` | turns per task per worker, revisions included (default 3) |
| `--review-rounds` | revisions a reviewer can ask for (default 1) |
| `--minutes`, `--budget` | when to stop: wall time, and dollars as the harnesses report them (a turn that reports none counts as 0) |
| `--check-image` | the image the tests run in |
| `--url` | the harness-interface server (default `http://127.0.0.1:8000`) |
