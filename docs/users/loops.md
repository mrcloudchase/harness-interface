# Run harnesses in a loop

"Stop prompting your harness; write a loop around it." Instead of you prompting a harness,
reading what it did and prompting again, a program does. You engineer four things instead of
prompts:

| | |
|---|---|
| **The goal** | what "done" means, written once: a spec and acceptance tests |
| **The verifier** | a check the harness can't argue with, run outside it: the tests |
| **The feedback** | what the next turn is told: the failures, verbatim |
| **The stop rules** | time, budget, tries, and the same failure twice |

harness-interface suits this. Every turn is one request, and `previous_response_id` continues
it. Each record carries the cost, and each turn's diff and files can be read. Every turn is
sandboxed, so a loop can run unattended. And because every harness takes the same request, a
loop can escalate from one harness to another, or have one review another's work.

## The build loop example

[examples/build-loop/](../../examples/build-loop/) is a complete loop in one file, `loop.py`. It
builds a project from a spec and an acceptance suite:

```
plan ─► for each task: build ─► verify ─► review ─► checkpoint
                         ▲        │ fail: feed back; after N tries, roll back and escalate
                         └────────┘
```

- The tests run in a throwaway container. Edits a harness makes to them are thrown away.
- Accepted work is committed in a git repository the loop owns, and anything else is rolled back.
- A different harness reviews each passing change, but the tests decide. An objection a change
  is accepted over is shown in the result.
- At its deadline or budget, it cancels the run in flight and stops cleanly. It resumes from its
  saved state.
- Every harness's own output and every turn's diff are shown as it works.

Its README has the steps to run it, and every option.

## Watch one

Given 20 minutes and a $15 budget, the build loop built the example project, `switchboard`, from
its spec. It took 5 minutes, and every one of the 16 acceptance tests passes:
- **Claude Code** built two of the plan's six tasks, each passing its tests on the first try. The
  other four were already passing by the time the loop reached them. It reported $1.21.
- **Codex** reviewed each change, and caught real problems:
  - name validation that accepted a trailing newline, and timeouts that refused fractions: fixed;
  - a truthiness check that let an empty `previous_run_id` through: fixed;
  - an endpoint that blocks the whole server while a command runs, and timeout output that can
    fail to decode. After the one revision round the passing tests decided, and the change was
    accepted with the objection shown in the result.

Two lessons from that run:
- **A reviewer finds what the tests miss.** No acceptance test runs two commands at once, or
  prints invalid UTF-8 before timing out. When a review turns up a real bug, add a test for it,
  so the tests decide it next time.
- **A budget counts only what's reported.** Codex reports tokens, not dollars, so its reviews
  aren't in the $1.21. The loop says how many turns reported no cost.

![The build loop building switchboard, at 6× speed](../media/build-loop.gif)

The full recording is [docs/media/build-loop.cast](../media/build-loop.cast). Play it with
[asciinema](https://asciinema.org):

```bash
asciinema play docs/media/build-loop.cast            # in real time; press space to pause
asciinema play -s 4 -i 1 docs/media/build-loop.cast  # 4× speed, idle gaps cut to a second
```

## Write your own

A loop is a few calls to the API, around whatever check you trust:

```python
import httpx

api = httpx.Client(base_url="http://127.0.0.1:8000", timeout=None)
record = api.post("/responses", json={"model": "claude-code", "input": "Make the tests pass."}).json()
for attempt in range(5):
    ok, failures = run_my_check(record)                  # yours: tests, a build, an eval
    if ok:
        break
    record = api.post("/responses", json={"model": "claude-code", "input": failures,
                                          "previous_response_id": record["id"]}).json()
```

`GET /responses/{id}/diff` and `/files` give a check what the harness changed. `harness.cost_usd`
on each record gives a budget, and `POST /responses/{id}/cancel` gives a deadline.
