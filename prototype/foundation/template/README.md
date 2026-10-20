# Harness folder template (contract v1)

Copy this folder to start a harness: `cp -r template ../harnesses/<name>`, then replace
`install.sh`, `run.sh`, `adapter.py` and `home/`, and delete `standin.py`. Keep `hi_adapter.py`
byte-identical (`hirun.py check <folder>` and `tests/test_foundation.py` enforce it; `hirun.py run`
refuses a drifted copy).

```
<name>/
  harness.json    what the runner needs to know (below); unknown or missing fields are errors
  install.sh      installs the pinned CLI into $HI_TOOLS (executables in $HI_TOOLS/bin)
  run.sh          maps HI_* onto the CLI's own settings, then `exec python3 -u adapter.py`
  adapter.py      drives the CLI: subclass hi_adapter.Adapter (start, on_line, steer, stop)
  hi_adapter.py   shared plumbing, identical in every folder (why: see below)
  home/           any tree; copied into $HOME before every response (CLI settings, skills, ...)
  standin.py      template only: the fake CLI (counts with sleeps, steers, abort, resume)
```

## harness.json — every field

| field | meaning |
|---|---|
| `name` | `[a-z0-9-]+`; names the tools dir `tools/<name>-<hash>` |
| `description` | one line for people: what it is, what it speaks, its caveats |
| `provider` | default provider `{url: "https://…", api}`; used when a request names none. `api` must be in `apis` |
| `apis` | API shapes the harness speaks: subset of `anthropic-messages`, `openai-responses`, `openai-chat` |
| `install.egress` | hosts the install container may reach (CONNECT door allowlist), e.g. `registry.npmjs.org`, `pypi.org`, `files.pythonhosted.org` |
| `install.timeout_s` | install is killed and discarded after this |
| `files` | `{path: template}` written into the workspace before every response, after `home/`; `{instructions}` is replaced; an empty result is not written. Paths are relative to the workspace and may target `.home/…` (e.g. `.home/.claude/CLAUDE.md`) |
| `run.interrupt` | `steered` (stdin lines reach the running work), `continued` (stop, then resume the CLI's conversation with the text), `responded` (stop, start again in the same workspace) |
| `run.stdout` | media type of stdout: `application/x-ndjson` (preferred) or `text/plain` |
| `run.timeout_s` | a response is stopped (SIGINT) after this, then killed after `stop_timeout_s` |
| `run.stop_timeout_s` | grace between SIGINT and the kill. Must exceed the adapter's `stop_grace_s` |

Cut from v0: `sandbox` (one base image for all), `run.argv` (always `bash run.sh`), `run.env`
(set it in run.sh). There is no run-time egress field: a session reaches only its provider.

## What a harness is given

Environment (exactly this; nothing else from the host leaks in):

| var | value |
|---|---|
| `HI_WORKSPACE` | the workspace; also the cwd. Same path inside and outside the sandbox |
| `HOME` | `$HI_WORKSPACE/.home` (persists across responses; resume state lives here) |
| `HI_HARNESS_DIR` | this folder, read-only |
| `HI_TOOLS` | the cached tools dir, read-only; `PATH` starts with `$HI_TOOLS/bin` |
| `HI_OUTPUT` | where to write the result JSON (outside the workspace) |
| `HI_MODEL`, `HI_RESUME` | the request's model and resume id (`""` when none) |
| `HI_PROVIDER_URL`, `HI_PROVIDER_API` | where model calls go and their shape; only when a provider is given |
| `HI_PROVIDER_KEY_FILE` | a file holding the credential to send (read-only). With the default gateway it holds a per-session token and `HI_PROVIDER_URL` is `http://hi-door-…:8080`: send it exactly as you would a key |
| `HTTPS_PROXY`, `https_proxy` | the egress door (sandbox only). Nothing else is reachable |
| `NO_PROXY`, `no_proxy` | `127.0.0.1,localhost[,door]`: loopback servers inside the run work |

stdin: line 1 is the request, compact JSON `{"task","instructions","model","resume","metadata"}`.
stdin stays open in every mode. For `steered`, each later line is one JSON string (new text).
**EOF = stop gracefully.** **SIGINT** (to the adapter's process group, via tini) **= stop gracefully**;
a kill follows `run.stop_timeout_s` later. `/tmp` is writable (512 MB); the root is read-only.

## What it gives back

stdout and stderr (streamed), workspace changes, and `$HI_OUTPUT`:
`{answer, status, resume, usage, cost_usd, steers}`, status `running|ok|fail|stopped`.
Write it early (`status: running` + `resume` as soon as the id is known) and atomically (tmp +
rename; `Output.write` does both), and again at the end. `stopped` = stopped by the user, resumable.
Status comes from the CLI's events, never its exit code. `steers` = steer lines the CLI accepted.
`usage`/`cost_usd` are for this response only (diff cumulative counters).

## The adapter (hi_adapter.Adapter)

`main()` reads line 1, writes a known resume early, then runs one event loop over the CLI's stdout
lines, stdin steers, EOF and signals. You define:
- `start(request)`: `self.spawn(argv)` the CLI (own session, cwd = workspace, loopback not proxied),
  send it the task (prepend `instructions` if the CLI ignores AGENTS.md);
- `on_line(source, line)`: pass events on with `self.emit`, `self.out.write(resume=…)` early,
  `self.accepted_steer()`, and `self.finish(status, answer=…, usage=…)` when the CLI says done and
  nothing is queued;
- `steer(text)`: the CLI's steer while busy (or a new prompt when idle);
- `stop()`: the CLI's own graceful stop (never a plain SIGINT to it); after `stop_grace_s` the
  loop finishes `stopped` and kills the CLI's process groups.

## Why hi_adapter.py is copied, not shared

A folder must run from itself + its tools dir + the base image, and the contract must stay
env + stdin + files: if the runner injected a library, the library would become contract surface
that every future runtime has to ship, and a folder could not be read or run on its own. A copy is
~200 lines, identical by test; changing it means changing every folder in one commit, on purpose.
