# Stage 2 report: claude-code

`R/harnesses/claude-code/`, 2026-10-20, Claude Code **2.1.304** (the npm `latest` dist-tag, published 2026-10-19; checked
with `npm view` today). Proofs: `python3 R/harnesses/claude-code/proof/prove.py local|docker gateway|docker file|deepseek|deepseek-file|extras|audit`
through the foundation's `hirun.py`, imported and **unmodified**: a subclass of `hirun.Run` steers or SIGINTs when
`count.txt` reaches 3 lines and audits the key while the run is live. There is one JSON per run in `proof/runs/`, plus `proof/results-*.json` and `proof/*.log`.

## Verdict
**Works. Tier: `steered`**, both local and docker, with both secret modes and with both providers. All 19 checks passed (plus 3 AGENTS.md probes); one Anthropic
run: the Anthropic key **ran out of credit** at 06:36, mid-proof (`400 "Your credit balance is too low"`, confirmed with a direct
call). That run is `docker-file-stop`. The adapter reported it correctly as `status: fail`, answer "Credit balance is too low", exit 0, which
shows that status comes from events and not from the exit code. I re-ran file-mode stop + continue on DeepSeek, and it passed. docker-file's 3 passing checks are in `proof/docker-file.log` only: prove.py crashed on the missing count.txt, so `results-docker-file.json` was never written.
`hi_adapter.py` is byte-identical to the template (`hirun.py check`: identical, foundation unit tests 7/7 OK).

## The folder
| file | what it does |
|---|---|
| `harness.json` | provider `https://api.anthropic.com` / `anthropic-messages` (the only shape); install egress `registry.npmjs.org`, 900 s; `files: {".home/.claude/CLAUDE.md": "{instructions}"}`; `run`: steered, ndjson, 1800 s, stop_timeout 20 s (> adapter grace 15 s) |
| `install.sh` (10 lines) | `npm i -g --prefix $HI_TOOLS @anthropic-ai/claude-code@2.1.304`, then asserts `claude --version` = 2.1.304. The postinstall runs offline: it hard-links the native `claude-code-linux-x64` binary (glibc; npm skips musl/other platforms by `libc`/`os`/`cpu`). Tools dir **276 MB**; no node is needed at run time |
| `run.sh` (18 lines) | `IS_SANDBOX=1` (bypassPermissions as root, local), `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, `ANTHROPIC_BASE_URL=${HI_PROVIDER_URL%/v1}`, `ANTHROPIC_DEFAULT_HAIKU_MODEL`/`ANTHROPIC_SMALL_FAST_MODEL=$HI_MODEL` (no claude-haiku id reaches another provider); **no key in env** |
| `home/.claude/settings.json` | `{"apiKeyHelper": "cat \"$HI_PROVIDER_KEY_FILE\""}`: claude reads the key file itself (`init.apiKeySource: "apiKeyHelper"`), so the value is never exported to the CLI or the model's shell |
| `adapter.py` (97 lines) | pattern P1. Starts `claude -p --input-format stream-json --output-format stream-json --verbose --replay-user-messages --dangerously-skip-permissions [--model M] --session-id <uuid4> \| --resume <id>`; writes `resume` before claude starts; task and steers are `user` lines; **done** = `result` and replays ≥ sent; **stop** = `control_request` interrupt, then the next `result` → `stopped`; `steers` = replays − 1; usage = sum of `result.usage`; `cost_usd` = `total_cost_usd` − the session total saved in `$HOME/.hi-cost/<sid>` (2.1.304's total is cumulative over resumes) |
| `hi_adapter.py` | the template copy, unchanged |
| `proof/` | prove.py + evidence. Not part of the contract; the runner never reads it |

Instruction files on 2.1.304 (local, code-word test): workspace `AGENTS.md` alone → **KIWI** (read). AGENTS.md + `~/.claude/CLAUDE.md`
→ "MANGO, KIWI" (both). AGENTS.md + workspace `CLAUDE.md` + home → "MANGO, FIG" (**AGENTS.md ignored** when a workspace
CLAUDE.md exists). So `.home/.claude/CLAUDE.md` is the right target: it is always read, it stays outside the user's tree, and it never shadows the user's own AGENTS.md or CLAUDE.md.

## Evidence (model claude-sonnet-4-6 unless marked DS = deepseek-chat; times are hirun `seconds`)
| proof | local (gateway) | docker gateway | docker file |
|---|---|---|---|
| install | miss 6.3 s (warm npm cache on host) | **miss 29.5 s, then hit 0.0 s** (`claude-code-71fbfdf7ef14`); door: 3× allow registry.npmjs.org | (hit) |
| one-shot + instructions ("2+2", "end with PAPAYA") | ok "4\n\nPAPAYA", 3.4 s, 4 events | ok, 3.9 s | ok, 4.3 s |
| resume ORCHID (run 2 `--resume`, same id) | ok "ORCHID", 1.7 s | ok "ORCHID", 3.3 s | ok "ORCHID", 18.1 s (API 16.8 s: provider latency) |
| steer after 3 numbers | ok, steers 1/1, done.txt=DONE, count stopped at **4**, 29.4 s | same: count 4, 29.3 s | same: count 4, 40.0 s |
| stop (SIGINT) at 3, then continue | stopped, **stop→exit 0.09 s**, count stays 3; "…got through number 3 before being stopped." | stopped, **0.30 s** via tini, count 3; "…got through 3 before being interrupted." | Anthropic: credit exhausted (fail, correctly). **DS: stopped 0.19 s**, count 3; "…had completed 1, 2, and 3 when you interrupted." |

Event shapes: one-shot = `system/init`, `user+replay`, `assistant`, `result/success`. Steer run = 1 init, 2 replays, 9
assistant, 5 tool `user`, 9 `system/thinking_tokens`, **one** `result/success` (the steer merged into the running turn). Stop =
our `hi.stop`, `control_response`, `result/error_during_execution`, then the adapter finishes `stopped` and closes stdin.
In all steer runs the steer went in when count.txt had 3 lines (stdout line 18–21), and one more number was already in flight.

**Provider swap (docker, gateway, same folder):** `--provider-url https://api.deepseek.com/anthropic --model deepseek-chat`:
one-shot "2+2 = 4.\n\nPAPAYA" 4.7 s; resume "ORCHID" (it also saved it to auto-memory, see open issues); steer: done.txt=DONE,
count 4, 17.5 s, 460 stdout lines (thinking_tokens). Gateway log: `POST /anthropic/v1/messages -> 200` only. File mode on DS: one-shot ok, stop/continue (above).
stderr carries `[claude-code:unrecognized_model] {"model":"deepseek-chat"}` (harmless). `cost_usd` uses Claude's price table (0.042 for "2+2"), so it is **wrong** for DS.

## Egress (provider only)
- gateway mode, CONNECT allowlist empty: **0 CONNECT attempts** in every run; only `gateway POST /v1/messages`
  (1 per model call; there were no background calls on 2.1.304 `-p`). On a stop the gateway logs `gateway error IncompleteReadError`: the client dropped the interrupted stream. Harmless.
- file mode: exactly **1** `door allow api.anthropic.com:443` (or `api.deepseek.com:443`) per run (one keep-alive connection); nothing else is tried.
- Without `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` (`prove.py extras`, DS): **2× `door deny api.anthropic.com:443`** in both
  modes; the run was unharmed (ok, 3.7 s). So the switch is not needed for correctness, but it keeps the door log clean and saves the 2 denied connects.
  2.1.304 does not use DNS (proxy CONNECT only). The run needs no other host.

## Secrets: gateway vs file (key = the real Anthropic/DeepSeek key, searched byte-wise, never printed)
| where | gateway | file |
|---|---|---|
| during the steer run: `docker inspect` run / door | no / no | no / no |
| host `/proc/*/cmdline` (ps) | no | no |
| host `/proc/*/environ` of the docker client + every container pid; any new holder | none | none |
| environ of all processes inside the sandbox (`docker exec … cat /proc/*/environ; env`) | no | no (apiKeyHelper keeps it out of env) |
| readable by the model's shell | no (it can read only the token) | **yes**: the key file is mounted ro, by design of (b) |
| after all 31 runs: base image `hi-base:80d60e8c2bde` (docker save), both tools dirs, install logs, 23 workspaces + `.home`, 31 run-log dirs, proof dir | none | none |
| my leftovers (containers, networks, `/dev/shm/hi-*`) | 0 | 0 |

Where the CLI puts what it was given: **nowhere on disk**. The token (gateway) and the key (file) were found in no file of any
workspace or `.home` (`.claude.json`, transcripts, backups, `sessions/`, memory). The value comes from apiKeyHelper at run
time and stays in memory. The machine's own `EXT_ANTHROPIC_API_KEY`/`DEEPSEEK_API_KEY` in dockerd, containerd and shells was
excluded as pre-existing. The `hi-*` containers and shm dirs seen during the audit belonged to other agents' concurrent runs (session ids not mine).
**Recommendation: gateway.** It worked unchanged for both providers (claude sends the token as `x-api-key`, and http:// base URLs are fine).
Use file only if the gateway is unavailable. Both work with the same folder.

## Contract friction
1. **Stale instructions.** `files` skips an empty render, so a response without instructions keeps the previous one's
   `.home/.claude/CLAUDE.md` (`extras`: run 1 with PAPAYA, resumed run 2 without → the file is still there, answer "6\n\nPAPAYA").
   Fix in the runner: delete (or empty) a `files` target whose template renders empty.
2. **The upstream is hidden behind the gateway.** `HI_PROVIDER_URL=http://hi-door-…:8080/anthropic` does not say which
   provider is behind it, so the adapter cannot tell that the CLI's `total_cost_usd` (a Claude price table) is meaningless for DeepSeek.
   Proposal: cost belongs to the gateway, which sees every response's `usage`. Failing that, pass the upstream identity (e.g. `HI_PROVIDER_NAME`) so the adapter can null the cost.
3. **Key as a file worked well.** Claude Code's `apiKeyHelper` turns `HI_PROVIDER_KEY_FILE` into a CLI-native read, so run.sh
   exports no secret. `home/` was the right place for it: the CLI never rewrites `settings.json`, so the copy before every response is safe.
4. Given but unused: `HI_PROVIDER_API` (one shape only); request `instructions` (handled via `files`); `metadata`;
   `HI_RESUME` env (the adapter uses line 1's `resume`, the same value: two channels for one fact; I suggest keeping one); `HI_TOOLS` (only via `PATH`).
5. Needed but not given: nothing blocking. The adapter keeps one piece of its own state (`$HOME/.hi-cost/<sid>`, for per-response cost). `$HOME` served for it.
6. `hi_adapter.py`: **no change needed**. Its loop, early `resume`, stop grace and `_reap` (close stdin → claude exits; rc 1
   after an interrupt on 2.1.304, ignored as intended) fit P1 directly. The adapter is 97 lines, 4 methods + 2 cost helpers.

## Open issues
- Anthropic credit ran out at 06:36. Not covered on Anthropic in docker file mode: stop + continue (covered on DS, and on Anthropic with the gateway and locally).
- 2.1.304 turns on **auto memory** (`.home/.claude/projects/<slug>/memory/`). The DS model saved "ORCHID" there. It persists in the
  workspace across sessions, a second memory beside the transcript. `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` exists in the binary but is untested and not set; the owner should decide.
- A steer that lands after the model's last tool call runs as a second turn. The adapter waits for the second `result` (replays ≥ sent).
  This case was proven in the survey (e4 "late") and not re-run here. `queued_turn_count` is still not used.
- `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` is set but was not exercised (no run used `run_in_background`).
- The model's Bash runs as uid 1000 with `bypassPermissions`. In file mode it can `cat $HI_PROVIDER_KEY_FILE`. That is inherent to (b), and one more reason for the gateway.
- A version pinned 1 day after release (as asked). The tools dir is 276 MB per version, and it would double with an arm64 or musl base.
