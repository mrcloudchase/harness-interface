# Keeper: a self-managing project

**Specification, v0.3**

Keeper is a spec for making a GitHub repository manage itself. One person owns its vision and
spends about an hour a week on it, while coding agents build and maintain it with Linux-kernel
level rigor.

This spec is the portable part. Each project carries its own implementation of it inside its own
repository, and shares no other repo, App or service. Everything runs as GitHub Actions workflows
in that repository, using only the credentials those workflows are given: the built-in
`GITHUB_TOKEN` and the repository's secrets.

harness-interface is the first project to run Keeper. Its implementation (`.keeper/`,
`keeper.toml`, the two workflows) is the reference; §13 says how to port it.

---

## 1. Outcome

| The human | Keeper |
|---|---|
| owns `VISION.md`: north star, principles, ranked themes, non-goals | turns the vision into issues, acceptance tests and changes |
| approves human-tier changes, such as the execution layer | builds, reviews, merges, releases and maintains everything else |
| answers what only they can decide (§9.2) | escalates exactly those things, and nothing else |
| reads one weekly digest | reports everything, so the human is never surprised |
| holds the pause switch and the budgets | runs within them |

Success means:
- the human spends about 60 minutes a week;
- every change on the work branch traces back to a theme in `VISION.md`;
- no regression survives the next nightly run;
- cost per accepted change goes down over time.

---

## 2. Principles

1. **KISS.** The plainest mechanism that works. Use GitHub's own features before building anything.
2. **DRY.** Every fact has one home in the repository: the vision in `VISION.md`, the configuration
   in `keeper.toml`, each loop in its document, each role in its prompt.
3. **SRP.** Each workflow job, module, class, loop and prompt does one job.
4. **OOP.** Things with state and identity are objects (`Config`, `Workspace`, `Memory`,
   `Governor`, `Loop`); the rest is functions and data.
5. **Negative space.** What must never happen is made impossible by token permissions, rulesets
   or the engine, and has a test (§12).
6. **Pick the right kind for each job:** deterministic first, then a one-shot prompt, then a loop (§4).
7. **Self-contained.** The repository holds everything Keeper is. Nothing outside GitHub and the
   model providers.
8. **Workflow credentials only.** Every action is taken by a workflow job using `GITHUB_TOKEN`,
   with only the permissions its kind needs, plus repository secrets for the providers.
9. **GitHub is the only state:** issues, PRs, labels, comments, statuses, Discussions, branches,
   releases. No database.
10. **Agents propose, workflows act.** An agent never holds a credential. It changes files in a
    sandbox, and the workflow decides what to do with them.
11. **Checks only grow.** Agents add or tighten tests and rules; removing or weakening one fails
    the Gate.
12. **The project improves itself.** Agents judge, and the Evolve loop rewrites the project's loops
    and prompts. Progress is measured (§11).

---

## 3. Architecture

```
the project's repository
├── VISION.md                      the human's: direction
├── AGENTS.md                      the project's principles, layout and commands
├── keeper.toml                    the configuration (§7.3)
├── .keeper/
│   ├── engine/                    the engine (§8): standard-library Python, a client of harness-interface
│   ├── loops/*.toml               one document per loop (§6)
│   ├── prompts/*.md               one prompt per role (§5.3)
│   └── tests/                     the engine's tests, including every rule in §12
└── .github/
    ├── workflows/keeper.yml       the entry workflow: events, schedules and dispatches → tasks
    ├── workflows/keeper-run.yml   the reusable workflow every task runs through
    ├── actions/keeper-setup/      disk space for the sandbox image, and uv
    ├── CODEOWNERS                 generated from keeper.toml
    └── ISSUE_TEMPLATE/            task and bug forms

inside an agent job, on the runner:
  harness-interface (Docker runtime, no credentials in its environment) runs each agent turn
  in a fresh sandbox that can reach only its model provider; output, diff and cost are recorded
```

**How a project gets Keeper:** a human gives this spec, a `VISION.md` and a `keeper.toml` to a
coding agent in a one-off bootstrap session, or copies the reference implementation. The human
reviews and merges it. From then on the project maintains its own copy, and the Evolve loop
improves its loops and prompts.

**Spec version:** `keeper.toml`'s `spec` says which version of this spec the project implements.
Bringing in a later version is a human-tier PR.

---

## 4. The three kinds of work

| Kind | Use it when | Runs as | Changes code? |
|---|---|---|---|
| **Job** (deterministic) | the rule can be written as code | plain code in a workflow job | only through its own fixed logic |
| **Prompt** (one agent run) | one judgment, where feedback wouldn't change the next step | one turn | no: it writes labels, issues, comments and posts |
| **Loop** | feedback changes the next step, and a check can say when it's done | turns until it reaches an end state | yes, through a branch and a PR |

---

## 5. Catalogue

### 5.1 Jobs (deterministic)

| Job | Trigger | Does |
|---|---|---|
| **Gate** | a PR opened or updated by a person, a human review, or a dispatch | checks out the PR head; runs every `[checks]` command; re-runs a failure once, and a pass the second time is a flake (filed, not blamed on the PR); applies the rules `tests_only_grow`, `size_budget`, `commit_format`, `themed`, `verified`; holds human-tier paths until the human approves this exact commit, unless the human wrote the PR. Sets the commit status `keeper/gate`. A Keeper PR that passes is dispatched to Merge. |
| **Merge** | a dispatch from Gate | squash-merges a Keeper PR whose `keeper/gate` is success, with its trailers (§11). The promotion PR is merged with a merge commit. Then dispatches the follow-ups (§5.4). |
| **Release** | a follow-up of a Keeper merge that changed `CHANGELOG.md` on the release branch | dispatches the project's own release workflow, which tags the newest changelog section if it is untagged |
| **Nightly** | schedule | runs `[live]` on the work branch. Green: records the commit and counts the streak; after `soak` green runs on a separate work branch, dispatches Promote. Red: files a regression issue with the last green commit, and dispatches Revert. |
| **Revert** | a dispatch from Nightly | finds the culprit (the only commit since the last green, or `git bisect run` with the live command), writes its diff into the regression issue, opens a revert PR, and dispatches Gate. Merging it dispatches Repair. |
| **Promote** | a dispatch from Nightly, when `work` ≠ `release` | opens a PR from the work branch to the release branch, verified by the streak, and dispatches Gate |
| **Backport** | a follow-up of a merge carrying `Cc: stable`, if `stable_branch` is set | cherry-picks the merge onto the stable branch and opens a PR |
| **Labels** | a follow-up of a change to `VISION.md` | creates the base labels and one `theme:<slug>` per theme |
| **Owners** | a follow-up of a change to `keeper.toml` | opens a PR regenerating `CODEOWNERS` from `[tiers]` |
| **Status** | daily, and after every merge | rewrites the pinned "Keeper status" issue (§9.4) |

The Governor is not a job but the first step of every agent turn: the pause switch, the budgets,
and the open-PR limit.

### 5.2 Prompts (one run each)

| Prompt | Trigger | Writes |
|---|---|---|
| **Plan** | weekly, or a change to `VISION.md` | an epic per theme, with sub-issues that each carry acceptance criteria (at most 6 new a run, never a duplicate title); an RFC issue, labelled `rfc` and `needs-human`, for anything the vision leaves open. Dispatches Triage for each new task. |
| **Triage** | an issue opened by the human, or a dispatch from Plan | `keeper`, a type label and a theme label; then `agent:ready` and a dispatch to Spec, or its questions and `needs-human` |
| **Escalate** | a loop ending blocked, stalled or exhausted | a comment on the same issue: the question, the options, a recommendation, the evidence; adds `needs-human`, removes `agent:ready` |
| **Decide** | a follow-up of merging a PR labelled `design` | a decision record in Discussions → Decisions |
| **Digest** | weekly | the weekly post in Discussions → Announcements (§9.3) |
| **Answer** | a comment by the human containing `@keeper` | a reply in the thread, from the thread, Keeper's record of the item, and the project's status |

A prompt that acts on its answer (Plan, Triage) reads it from `keeper.json`, the one channel for a
structured answer. A prompt whose answer is posted (Escalate, Decide, Digest, Answer) is told to
reply with the text alone and write no files.

### 5.3 Role prompts
A role is a prompt in `.keeper/prompts/<role>.md` plus a harness from `[roles]`. A
`checker-<name>` role runs on the `checker` harness unless `[roles]` names one for it. Every role
is also given `AGENTS.md` and `VISION.md`, which no prompt repeats.

| Role | Used by |
|---|---|
| `planner` | Plan |
| `maker` | every loop's turns, on the harness of each role in its `escalate` list |
| `checker-<name>` | judges: `correctness`, `principles`, `security`, `docs`, `simplicity` |
| `writer` | Triage, Escalate, Decide, Digest, Answer |

### 5.4 Follow-ups
After Keeper merges a PR, it dispatches what that PR's paths and labels need. A push by the human
to the work or release branch sets off the same tasks, except Release, which the push starts itself.

| When the change | Dispatch |
|---|---|
| touches `VISION.md` | Labels, Plan |
| touches `keeper.toml` | Owners |
| touches `CHANGELOG.md` on the release branch, merged by Keeper | Release |
| is a revert, with `Regression: #n` | Repair on #n |
| carries `Cc: stable`, with a stable branch set | Backport |
| is labelled `design` | Decide |
| anything | Status |

---

## 6. Loops

### 6.1 What every loop has
| Part | Rule |
|---|---|
| Trigger | a dispatch, the human's label, or a schedule; a scheduled loop works on an issue of its own, one a week |
| Goal | the loop document's goal, then the issue's title, body and acceptance criteria |
| Branch | `keeper/<issue>`, from the work branch or from where an earlier loop left it |
| Execution | maker turns. Within a run, retries continue one conversation (`previous_response_id`). Each role in `escalate` starts fresh from the branch's starting point, with the maker's prompt on its own harness. |
| Verification | the document's verifiers, cheapest first, stopping at the first failure; at least one at level 1 or 2 (§6.2) |
| End states | `success`, `no_op`, `blocked`, `stalled`, `exhausted`; an error or a spent budget is never `success` |
| Feedback | the failures, verbatim, are the next turn's input |
| Memory | GitHub only (§8.3) |
| Brakes | a try limit per role; the run, day and week budgets; the same failure twice means `stalled`, and the next role takes over |
| Publishing | `success` commits and pushes the branch, then opens a PR with a verdict for that commit and dispatches Gate, or, for a loop that doesn't open one, dispatches its `then`. A failure dispatches Escalate. The issue carries one `end:<state>` label, the latest. |

### 6.2 The verification ladder
| Level | Verifier | Example |
|---|---|---|
| 1 | `command` | a `[checks]` command, all of them (`checks`), or any command; `expect = "fail"` for tests that must fail first; `repeat` for flakes |
| 2 | `rule` | `tests_only_grow`, `tests_only`, `size_budget`, `size_decreased`, `keeper_paths`, `no_workflows` |
| 3 | `live` | the `[live]` command, or `[compat]`'s; the only commands given provider keys |
| 4 | `judge` | a checker role's verdict, in `keeper.json`: approve, or changes citing file:line. Roles from the document, or from `[reviewers]` for the changed paths. |
| 5 | human | the human's approving review of the exact head commit, applied by the Gate to human-tier paths |

A loop succeeds only when every verifier it lists passes. Judges count.

### 6.3 Default loops

| Loop | Trigger | Done when | Verifiers | Then |
|---|---|---|---|---|
| **Spec** | `agent:ready`, or a dispatch from Triage | tests encoding the criteria fail on the current code | command `test`, expect fail; rules `tests_only`, `tests_only_grow`, `no_workflows` | Build, on the same branch; no PR |
| **Build** | a dispatch from Spec | every check passes and the judges approve | command `checks`; rules `tests_only_grow`, `size_budget`, `no_workflows`; judge | a PR, then Gate |
| **Repair** | a dispatch after a revert merges | the reverted change re-lands with its fix | command `checks`; rules; live | a PR |
| **Flake** | a dispatch from Gate | the test passes 5 runs out of 5 | command `test` ×5; rules `tests_only_grow`, `no_workflows` | a PR |
| **Upgrade** | weekly, if `[upgrade].targets` is set | the pins are current and checks and the live run pass | command `checks`; rules; live | a PR |
| **Strengthen** | weekly, if `[rigor].mutation` is set | the mutation score reaches its target | command `mutation`; rules `tests_only`, `tests_only_grow` | a PR |
| **Simplify** | weekly, if `[rigor].size_budget` is set | fewer lines, every check passing | command `checks`; rules `size_decreased`, `tests_only_grow`, `no_workflows`; judges `simplicity`, `principles` | a PR |
| **Docs** | weekly | the docs match the code | command `checks`; rules; judge `docs` | a PR |
| **Compat** | a dispatch, if `[compat].command` is set | the downstream projects' tests pass | command `checks`; rules; live `compat` | a PR |
| **Evolve** | weekly | the loops and prompts changed, Keeper's tests pass, and the replay (§8.4) accepts the last accepted builds again for no more than they cost | rule `keeper_paths`; command Keeper's tests; command the replay; judge `principles` | a PR |

A project adds a loop by adding a document to `.keeper/loops/`, with these fields: `name`, `goal`,
`verifiers`, and optionally `maker`, `escalate`, `tries`, `opens_pr`, `then`, `needs`. It never
adds engine code for one.

---

## 7. Files

### 7.1 `VISION.md` (the human's)
```markdown
# Vision
## North star        what this project is for, and for whom
## Principles        the rules no change may break
## Themes            ranked: `1. **Theme name**: what done looks like`; each becomes theme:<slug>
## Non-goals         what we will not do
## Constraints       budgets, platforms, licences, anything fixed
```

### 7.2 `AGENTS.md` (the project's)
How the code is laid out, the commands to run, the conventions, where each change goes. Every
agent is given it.

### 7.3 `keeper.toml`
Patterns are `fnmatch` globs on repository paths, where `*` also crosses `/`: `src/*` is
everything under `src/`. The reference is harness-interface's own `keeper.toml`.

| Section | Holds |
|---|---|
| `spec` | the spec version implemented |
| `[human]` | `login`: whose events start work and whose approval the human tier needs |
| `[branches]` | `work` (where PRs land), `release` (what releases come from), `soak` (green nightlies before promotion) |
| `[checks]` | name → command; every one must pass for any PR |
| `[live]` | `command`, and `secrets`: the only secrets it is given |
| `[tiers]` | `human`: paths only the human approves |
| `[reviewers]` | path pattern → checker roles; the first match per path |
| `[roles]` | `planner`, `maker`, `checker`, `writer`, and any `checker-<name>` → a harness |
| `[providers]` | name → `url`, and `key`: the name of the secret holding it |
| `[budget]` | `run_usd`, `day_usd`, `week_usd`, `open_prs`, `tries` |
| `[rigor]` | `size_budget` (`path`, `glob`, `lines`), `mutation`, `stable_branch`, and optionally `tests`, `test_pattern`, `assert_pattern` for a language other than Python |
| `[upgrade]` | `targets`: what the Upgrade loop keeps current |
| `[compat]` | `command`: the downstream projects' tests against this checkout |
| `[schedule]` | cron (UTC) → tasks; `keeper.yml` lists the same crons, and a test keeps them equal |

### 7.4 A loop document (`.keeper/loops/build.toml`)
```toml
name = "build"
goal = """Do this task. Any acceptance tests already written for it are in the project: make them pass
without changing them, keep every other check passing, and keep the change small."""
verifiers = [
  { kind = "command", run = "checks" },
  { kind = "rule", rules = ["tests_only_grow", "size_budget", "no_workflows"] },
  { kind = "judge" },
]
escalate = ["maker", "checker"]
```

### 7.5 The workflows (committed by the human)
- **`keeper.yml`** routes. It runs only while `KEEPER_ENABLED` is `true`. Its `route` job is
  read-only, runs `main.py route`, and outputs the tasks; its `run` job fans them out to
  `keeper-run.yml`, one concurrency group per task and item.
- **`keeper-run.yml`** runs one task in the job for its kind:

| Kind | Tasks | `permissions:` | Has |
|---|---|---|---|
| `gate` | Gate | `contents: read`, `pull-requests: write`, `issues: write`, `statuses: write`, `actions: write` | `GITHUB_TOKEN` |
| `write` | Merge, Release, Nightly, Revert, Promote, Backport, Labels, Owners, Status | the same with `contents: write` | `GITHUB_TOKEN`, secrets (for live runs) |
| `agent` | every prompt and loop | `contents`, `pull-requests`, `issues`, `discussions`, `actions`: `write` | `GITHUB_TOKEN`, secrets, a harness-interface server |

Every checkout is made with `persist-credentials: false`. `GITHUB_TOKEN` and the secrets (as
`KEEPER_SECRETS`, `toJSON(secrets)`) reach only the engine's step. Turn records are uploaded as an
artifact of every agent job.

---

## 8. Engine (`.keeper/engine/`)

### 8.1 Modules (one job each)
| Module | Responsibility |
|---|---|
| `config.py` | `Config`, `LoopDoc`, `Verify`, `Budget`: `keeper.toml` and the loop documents, refused if invalid |
| `router.py` | a GitHub event → tasks; only the human's events and dispatches start work |
| `tasks.py` | every task by name and kind; runs one; the scheduled loops' weekly issues; the replay |
| `jobs.py` | the deterministic jobs and the follow-ups |
| `prompts.py` | the one-shot prompts |
| `loop.py` | `Loop` runs a document to an `Outcome`; `publish` puts it on GitHub |
| `verifiers.py` | the ladder: `command`, `rule` (and `RULES`), `live`, `judge`, `human` |
| `roles.py` | what an agent is told: its prompt, `AGENTS.md`, `VISION.md` |
| `runtime.py` | the harness-interface client: providers and harnesses through `hi`, turns and files through the API |
| `workspace.py` | the runner's checkout: branches, applying changes, commits, pushes, commands, history |
| `github.py` | the REST and GraphQL calls Keeper makes, and nothing else |
| `memory.py` | the state comment on an issue or PR |
| `governor.py` | the brakes |
| `metrics.py` | what the status issue and the digest report, computed from GitHub |
| `env.py` | the credential-free environment everything Keeper starts runs in |
| `context.py`, `main.py` | what a task works with; the entry point |

### 8.2 A loop run
```
start = workspace.start("keeper/<n>", work)              # the branch, as origin has it, or new from work
since = merge_base(start, origin/work)                   # what the change is measured against
for role in doc.escalate:
    reset to start; a fresh conversation; forget the last failure
    for each try:
        governor.allow(this run's spend)          else → blocked
        turn = runtime.turn(harness(role), instructions(maker), goal + task + feedback,
                            files = seed if it is the conversation's first turn)
        record the turn's spend; apply its changes (never its own instruction files, .home, .hi, keeper.json)
        nothing changed and keeper.json says no_op  → no_op
        verdicts = verifiers, cheapest first, until one fails (a change to .github/workflows fails first)
        all pass → success (no change → no_op)
        same failure as the last try → next role
        feedback = the failures, verbatim
→ stalled, or exhausted
publish(outcome)
```

### 8.3 Memory
| What | Where |
|---|---|
| task | the issue: labels, body, acceptance criteria; epics through sub-issues |
| attempt | the branch `keeper/<n>` and its PR |
| loop state | `<!-- keeper:state {"loop", "attempts", "responses", "spend", "failure", "end", "branch", "data"} -->` on the issue or PR, edited in place |
| a loop's verdict | `<!-- keeper:verdict {"sha", "passed"} -->` on its PR, which the Gate's `verified` rule requires |
| nightly state | the status issue's state: the last green commit and the streak |
| turn records | harness-interface's records and logs, uploaded as workflow artifacts |
| spend | summed from the state comments of the items labelled `keeper` this week; never stored twice |
| decisions | Discussions → Decisions |

### 8.4 The replay
Evolve's check. It reruns the last two accepted Build tasks from the commits their PRs started
from, in throwaway worktrees, with the loops and prompts as Evolve changed them, and publishes
nothing. It passes if every one is accepted again for no more than it first cost.

### 8.5 Seeding an agent's workspace
The engine hands an agent the repository's tracked text files, at most 200 KB each and 4 MB in
all. Binaries are left out. An agent works on what it was handed; the workflow applies only what
it changed.

---

## 9. The human

### 9.1 The weekly hour
| Minutes | What | Where |
|---|---|---|
| 20 | read the digest | Discussions → Announcements (an issue labelled `announcements` if Discussions are off) |
| 25 | clear what's waiting | the status issue's "Waiting on you": issues and PRs labelled `needs-human` |
| 10 | steer: reorder themes, add or drop non-goals | a PR to `VISION.md` |
| 5 | ask anything | `@keeper …` in any thread |

### 9.2 What reaches the human (and nothing else)
1. a PR touching a human-tier path, with a review request;
2. an RFC: something the vision leaves open;
3. a loop that ended `blocked`, `stalled` or `exhausted` on every role;
4. Triage's questions about an issue it can't start;
5. a regression with no green commit to go back to;
6. a security advisory, through GitHub's private reporting.

### 9.3 The digest
```
Shipped, by theme      what merged, linked
Decisions made         one line each, linked to the record
Waiting on you         what, and the oldest
Health                 regressions, end states per loop
Cost                   spend against budget; cost per accepted change
Next                   what is ready
```

### 9.4 The status issue
A pinned issue, "Keeper status", rewritten daily and after every merge:
- what waits on the human;
- work in flight;
- what is ready for an agent;
- each loop's end states this week;
- regressions, spend against budget, and cost per accepted change.

### 9.5 Controls
| Control | How |
|---|---|
| Pause | set the repository variable `KEEPER_ENABLED` to anything but `true`; nothing routes |
| Budgets | `[budget]` in `keeper.toml` (human tier) |
| Direction | `VISION.md` (human tier) |

---

## 10. Designing around `GITHUB_TOKEN`

### 10.1 What the token can and can't do
| Fact | What Keeper does about it |
|---|---|
| Events it causes (a PR, a label, a push, a merge) **start no new workflow runs**, except `workflow_dispatch` | Keeper chains its own steps with `workflow_dispatch` on `keeper.yml` (`actions: write`). A merge by Keeper dispatches the release workflow too. The human's own actions arrive as ordinary events. |
| It **can't approve a PR it opened** | The required check is `keeper/gate`. It needs the loop's verdict for the head commit and, for human-tier paths, the human's approval of that commit. |
| It **can't change `.github/workflows/`** | Workflows are the human's by construction; a loop's change to them fails before it is pushed. |
| It **can't reach Projects** | The board is the status issue; themes are labels; epics have sub-issues. |
| **Issue types** are organisation-only | Type is a label: `epic`, `task`, `bug`, `regression`, `flake`, `rfc`. |
| It **can post to Discussions** but not create categories | The human creates them once; without them, posts become labelled issues. |
| It **expires with the job** and has an hourly API limit | Nothing long-lived holds it. |
| Its **permissions are set per job** | `keeper-run.yml` has one job per kind (§7.5); the default is `permissions: {}`. |

### 10.2 Keeping credentials from project code
The Gate runs a PR's tests on the runner, so code an agent wrote runs where the token is.
Keeper keeps them apart:
- Every checkout is made without persisted credentials.
- The engine passes the token to git only on the commands that reach GitHub (fetch, push,
  ls-remote), never on ones that run project code.
- Every command and subprocess the engine starts runs in `env.clean()`: the job's environment
  without anything named like a credential.
- Only `live` commands are given provider keys, and only those `[live].secrets` names. They run
  the project's own code with those keys, so use spend-limited keys.
- In Actions, the runtime refuses any turn that didn't run in a Docker sandbox.

### 10.3 Repository settings (once, by the human)
| Setting | Value |
|---|---|
| Actions → Workflow permissions | read-only by default; **allow GitHub Actions to create and approve pull requests** turned on |
| Ruleset on the work and release branches | require a PR; require the status `keeper/gate`; block force-pushes; no bypass |
| Variables | `KEEPER_ENABLED=true` |
| Secrets | the provider keys named in `[providers]` |
| Discussions | on, with categories Announcements, Decisions and Q&A |
| Security | private vulnerability reporting, secret scanning with push protection, Dependabot alerts |

Labels are created by the Labels job.

---

## 11. Rigor (the Linux kernel, applied)

| Kernel practice | Keeper |
|---|---|
| don't break userspace | no regressions: Revert first, then Repair; Compat runs downstream projects' tests |
| MAINTAINERS | `[tiers]` and `[reviewers]`; `CODEOWNERS` generated from them |
| one change per patch, bisectable | one task per PR, squash-merged, so each commit on the work branch is one change that passed |
| commit format and trailers | `area: summary`, then `Closes #n`, `Theme:`, `Keeper-Loop:`, `Regression:`, `Reverts:`, `Fixes:`, `Cc:`, `Reviewed-by: keeper/gate` |
| checkpatch | the Gate's rules |
| linux-next | `work = "next"`: changes land on `next`, soak through `soak` green nightlies, and Promote takes them to `release` |
| stable trees | `stable_branch` plus Backport |
| 0-day bot, KernelCI | the Gate on every PR; the Nightly live run |

**Metrics** (computed from GitHub by the status issue and the digest):
- cost per accepted change;
- end states per loop;
- regressions per week;
- what waits on the human;
- spend against budget.

---

## 12. Negative space: what can never happen

| Never | Enforced by |
|---|---|
| a push to a protected branch without a PR | the ruleset, with no bypass |
| a merge without `keeper/gate` | the ruleset's required status; Merge checks it too |
| a Keeper PR merged without its loop's verdict on that commit | the Gate's `verified` rule |
| a human-tier change by Keeper merged without the human | the Gate holds `keeper/gate` until `[human].login` approves the head commit |
| Keeper changes its workflows | `GITHUB_TOKEN` can't; a loop's change to them fails `no_workflows` before it is pushed |
| project code sees the token or an unnamed key | `env.clean()`; credentials only on git's remote commands; checkouts without persisted credentials |
| an agent turn outside a sandbox in Actions | `Runtime(sandboxed=True)` refuses the record |
| an agent's own files or build noise become part of a change | `Runtime.changes()` leaves out instruction files, `.home/`, `.hi/` and `keeper.json`; `.git/info/exclude` keeps out caches |
| a test deleted or weakened | the `tests_only_grow` rule, in the loops and at the Gate |
| a loop without a deterministic verifier | `LoopDoc` refuses it |
| a role without a prompt, or a harness | `Config` refuses it |
| `success` without every verifier passing | `Loop.run` |
| spend past budget | the Governor, before every turn |
| work started by anyone but the human | `route` acts only on the human's events and on dispatches |
| a scheduled task the workflow doesn't run | a test keeps `keeper.yml`'s crons equal to `[schedule]` |
| the human surprised | every end state, merge and decision reaches the status issue and the digest |

Each row has a test in `.keeper/tests/`, except the rulesets, which are GitHub's.

---

## 13. Porting Keeper to a project

1. **Copy** `.keeper/`, `.github/workflows/keeper.yml`, `.github/workflows/keeper-run.yml`,
   `.github/actions/keeper-setup/` and the issue forms from the reference.
2. **Write** `VISION.md` and `keeper.toml`, and make sure `AGENTS.md` describes the project.
   `keeper.toml`'s `[checks]` are the project's own commands. `[roles]` names any harness-interface
   harness.
3. **Make** the project's checks and its release workflow run from a clean checkout. Keeper
   dispatches a workflow named `release.yml` with `workflow_dispatch`.
4. **Settings** (§10.3), once. Then set `KEEPER_ENABLED=true`.
5. **Kick it off:**
   - run Labels, then Status (`gh workflow run keeper.yml -f task=labels`);
   - open an issue for the first task, or run Plan;
   - watch the status issue.
6. **Branching:** start with `work = release = "main"`. To soak changes first:
   - create `next` from `main`;
   - protect it like `main`;
   - set `work = "next"`.

   Promote then takes `next` to `main` after `soak` green nightlies.

---

## Appendix: words

| Word | Meaning |
|---|---|
| Job | deterministic automation |
| Prompt | one agent run that writes labels, issues, comments or posts |
| Loop | agent turns until verifiers decide an end state |
| Task | what one workflow run does: a job, a prompt or a loop, by name |
| Verifier | a check at a level of the ladder (§6.2) |
| Verdict | a loop's record that its verifiers passed on a commit |
| End state | `success`, `no_op`, `blocked`, `stalled`, `exhausted` |
| Human tier | paths only the human approves |
| Theme | a ranked line in `VISION.md`; every task belongs to one |
| Work branch | where Keeper's PRs land; the release branch is what releases come from |
