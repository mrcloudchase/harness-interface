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
| code passes the tests but is wrong or messy | a different harness reviews each passing change; its objections get one round of revision, but the tests still decide |
| it runs forever | `--minutes` and `--budget`: at either, it cancels the run in flight and stops cleanly |
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

Given 20 minutes and a $15 budget, the loop built switchboard from its spec in 7 minutes, for
$1.54 as the harnesses reported it. All 16 acceptance tests pass.

| Task | |
|---|---|
| 1. App structure and harness storage | Claude Code, 2 tries. Codex rejected name validation that accepted a trailing newline; fixed, then approved. |
| 2. Run execution | Claude Code, 2 tries. Codex flagged timeouts that killed only the process, not its group; accepted on passing tests after the one revision round. |
| 3. Timeouts | already passing after task 2; no turn spent |
| 4. Continuing runs | Claude Code, 2 tries. Codex caught truthiness checks on an id; fixed, then approved. |

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
| `--tries` | tries per task per worker (default 3) |
| `--review-rounds` | revisions a reviewer can ask for (default 1) |
| `--minutes`, `--budget` | when to stop: wall time, and dollars as the harnesses report them |
| `--check-image` | the image the tests run in |
| `--url` | the harness-interface server (default `http://127.0.0.1:8000`) |
