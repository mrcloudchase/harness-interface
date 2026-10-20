# Stage 1 report: foundation

`F` = `R/foundation/`, all run here on 2026-10-20. `python3 F/prove.py` re-runs every proof below (19 checks, ~2 min, all PASS; `F/proof/prove.log`, `F/proof/*.json`);
`python3 -m unittest discover -s F/tests` the fast ones (7, no Docker, all pass).

| file | what |
|---|---|
| `F/template/` | the folder to copy: harness.json, install.sh, run.sh, adapter.py, hi_adapter.py, home/, standin.py, README.md (every field) |
| `F/base.Dockerfile` | the base image, `hi-base:80d60e8c2bde`, **405 MB** |
| `F/hirun.py` | prototype runner: `base`, `check`, `install`, `run`, `clean` (stdlib, 645 lines incl. docs) |
| `F/door.py` | CONNECT door (reuses `egress.Door`) + provider **gateway** (new) |
| `F/probe/` | a CLI-less harness folder that probes the network from the install and run containers |
| `F/prove.py`, `F/tests/` | end-to-end proofs; unit tests (incl. "every hi_adapter.py copy is identical") |

## 1. Template layout and why
- `standin.py` is a fake CLI with an RPC mode (JSON commands in, NDJSON out): announces a session
  id first, counts to N with sleeps appending to `count.txt`, takes steers between steps ("count to K"
  moves the target), aborts gracefully, saves its session under `$HOME/.standin` after every step,
  `--resume ID` carries on, optionally calls its provider once (`GET /v1/models`), and runs an
  npm-installed helper from the tools dir. install.sh pins it by sha256 like any download.
- `adapter.py` (58 lines) subclasses `hi_adapter.Adapter` with 4 methods: `start`, `on_line`, `steer`,
  `stop`. Everything else (line 1, steer lines, EOF, SIGINT/SIGTERM, grace + killpg, atomic early
  HI_OUTPUT, own-session spawn, loopback NO_PROXY) is in `hi_adapter.py` (194 lines).
- **DRY:** `hi_adapter.py` is **copied byte-identical** into every folder. Enforced three ways: unit
  test over `F/*/` and `R/harnesses/*/`, `hirun.py check`, and `hirun.py run` refuses a drifted copy.
  Why not a runner-mounted library: it would become contract surface every future runtime must ship,
  and a folder could no longer be read, versioned or run on its own. Stage 2: `cp F/template/hi_adapter.py`.

## 2. The contract as implemented (v1)
**harness.json** (closed: unknown/missing fields are errors): `name`, `description`,
`provider {url, api}`, `apis [..]`, `install {egress, timeout_s}`, `files {path: template}`,
`run {interrupt, stdout, timeout_s, stop_timeout_s}`. Full table in `F/template/README.md`.
- Cut from v0: `sandbox` (one base image), `run.argv` (always `bash run.sh`), `run.env` (put it in
  run.sh, which exists anyway), `HI_TASK` and `HI_REQUEST` (the request lives in one place: stdin
  line 1), the key's value in env. Request `files` dropped from line 1 (the runner writes them).
- Added: `run.stop_timeout_s`, `install.timeout_s`, `provider` as `{url, api}` (a URL alone cannot
  pick a shape), status `running`/`stopped`, `steers`, `HI_PROVIDER_KEY_FILE`.

**Env** (exactly; host env is an allowlist, see §5): `HI_WORKSPACE` (=cwd, same path in and out),
`HOME=$HI_WORKSPACE/.home`, `HI_HARNESS_DIR` (ro), `HI_TOOLS` (ro; `PATH=$HI_TOOLS/bin:…`),
`HI_OUTPUT` (in a per-run dir **outside** the workspace, so the workspace diff stays the user's),
`HI_MODEL`, `HI_RESUME` (`""` if none), and with a provider `HI_PROVIDER_URL`, `HI_PROVIDER_API`,
`HI_PROVIDER_KEY_FILE`; sandbox: `HTTPS_PROXY`/`https_proxy` = door, `NO_PROXY`/`no_proxy` =
`127.0.0.1,localhost,<door>`. In this machine's sandbox also `SSL_CERT_FILE`, `NODE_EXTRA_CA_CERTS`,
`REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `GIT_SSL_CAINFO` = `/etc/hi/ca.pem` (egress TLS here is
re-signed; `HI_CA_FILE` overrides, absent file = nothing mounted).

**stdin:** line 1 = compact JSON `{task, instructions, model, resume, metadata}`. **Stdin stays open in
every mode** (one rule, not three); later lines = one JSON string each, sent only to `steered`
harnesses (`hirun` refuses `--steer-after-lines` otherwise); **EOF = graceful stop**.
**Signals:** `docker run --init -e TINI_KILL_PROCESS_GROUP=1`; stop = `docker kill --signal INT` →
tini → run.sh's group (run.sh `exec`s the adapter; the CLI is in its own session, so only the adapter
sees it and uses the CLI's own stop) → kill after `run.stop_timeout_s`. Local: `killpg(SIGINT)`.
**HI_OUTPUT** `{answer, status: running|ok|fail|stopped, resume, usage, cost_usd, steers}`, tmp+fsync+rename,
written when the resume id is known and at the end. The runner maps a cut-off `running` to `stopped`
if it asked for a stop and a resume id exists, else `fail`; it never reads the exit code as status.
**Result JSON** (`hirun run` stdout, and `<rundir>/result.json`): session, status, answer, resume,
usage, cost_usd, steers, steers_sent, stop (`requested|timeout|killed[+killed]`), stop_to_exit_s,
exit_code, files_changed {added, deleted, modified} (outside `.home`), workspace, tools, logs, door_log.

## 3. Base image, install and cache
- Base: `python:3.12.15-slim-trixie` + node 22.23.3 and npm (copied from `node:22.23.3-bookworm-slim`)
  + uv 0.9.5 (from `ghcr.io/astral-sh/uv:0.9.5`) + git + ca-certificates, user `hi` 1000:1000,
  `UV_PYTHON_DOWNLOADS=never`. No https fetch at build. Layers: python 119 MB, node 125, git+perl 99,
  uv 51, npm 11. **No tini**: `--init` is docker's tini and is what was proven; a non-Docker runtime
  would add `tini -g` as entrypoint (1 MB). Dropping git would save 99 MB if no harness needs it.
- `tools/<name>-<sha256(install.sh ‖ base image id)[:12]>/`; complete only when `.hi-installed`
  exists (written last); a failed/timed-out install deletes the dir; `flock` per dir. Install container:
  base image, LOCKDOWN+HARDENING, uid 1000, `--init`, its own `--internal` network + door allowing
  only `install.egress`, `HOME=/tmp`, folder ro, tools dir rw **at its final path** (npm/uv write
  absolute paths: a uv tool's bin is an absolute symlink into `$HI_TOOLS/uv/…`), no provider vars.
- Proven: miss 2.2–8.8 s then hit 0.2 s (docker), 0.7 s/0.16 s (local); install container reached
  registry.npmjs.org (200) and got 403 for api.anthropic.com, pypi.org, github.com, no DNS, no route;
  `uv tool install cowsay==6.1` (egress pypi.org, files.pythonhosted.org) ran from the ro mount in a
  run container. Only install.sh is hashed: anything else it reads must be pinned inside it.
- Local mode (`--local`) installs on the host into `tools/<name>-local-<hash>/` (host proxy, no door).

## 4. Proofs with the stand-in (all PASS, `F/proof/proof-basics-egress-secrets.json`)
- local and docker runs: `count to 6` + steer "count to 8 instead" after 4 lines → ok, "Counted to 8.",
  steers 1/1, `count.txt` added. Docker adds ~2.1 s per response (network + door + container).
- SIGINT stop through tini: stopped, exit 0, 0.45 s docker / 0.39 s local; the resumed run continues
  4…8 in the same workspace. An adapter that ignores the stop: killed at 2.2 s (stop_timeout_s 2).
- hard kill after 6 lines: HI_OUTPUT already `{status: running, resume: <id>}`, session saved at 4;
  `--resume` continues to 8 with count.txt exactly 1…8.
- run container (provider api.anthropic.com): CONNECT api.anthropic.com 200 + real `/v1/models` 200;
  registry.npmjs.org, pypi.org, github.com, api.openai.com 403; DNS fails; 1.1.1.1 and the docker
  host 172.17.0.1 unreachable; a 127.0.0.1 server inside is reachable with the proxy vars set.
- teardown: 0 `hi-*` containers, 0 `hi-net-*` networks, 0 `/dev/shm/hi-*` after every run.

## 5. Secrets: recommendation = (c) provider gateway; (b) file as fallback; never (a)
(c) The door also runs a plain-HTTP reverse proxy to the one provider. The harness gets
`HI_PROVIDER_URL=http://hi-door-<sid>:8080[/path]` and a key file holding a per-session token shaped
like a key (`sk-ant-api03-hi-…`/`sk-hi-…`). The gateway refuses any other credential (401), strips
auth/hop headers, adds the real key in the shape's header (`x-api-key` or `Authorization: Bearer`),
and forwards over TLS. The key reaches the door on its **stdin** (not argv, env or disk). Harness code
is identical under (b) and (c): read `HI_PROVIDER_KEY_FILE`, send it to `HI_PROVIDER_URL`.
In gateway mode the CONNECT allowlist is empty.

Matrix while a stand-in ran and after (`prove.py secrets`, Anthropic key, provider call 200 in all three):

| where the key was found | (a) env by name | (b) 0400 tmpfs file | (c) gateway |
|---|---|---|---|
| `docker inspect` run / door | **run: yes** / no | no / no | no / no |
| host `/proc/*/cmdline` (ps) | no | no | no |
| host `/proc/*/environ` | **docker client, docker-init, adapter, CLI** | no | no |
| readable by the sandbox (model's shell) | **yes** (env) | **yes** (file) | **no** (token only) |
| image, tools dir, workspace + .home, run logs, runner output | no | no | no |
| after teardown (shm, containers, environ) | gone | gone | gone |

(b) also leaks into the CLI's environ whenever run.sh must export the value (most CLIs): the template
hands the CLI the file path instead. Extra wins of (c): CLIs that write keys to disk (codex
auth.json, cline, minimax) write a token; the CLI needs no CA bundle for model calls (plain HTTP to
the door); usage is observable at one point. Also proven: OpenAI shape (Bearer swap, `/v1/models` 200)
and SSE streaming (`/v1/messages` stream=true, 10 events, incremental).
Found: this machine's shells and dockerd carry the key as `EXT_ANTHROPIC_API_KEY`; a denylist (`CLAUDE*`,
`ANTHROPIC*`…) passed it to every docker client. **Child env is now an allowlist** (PATH, HOME, LANG, TERM, proxy, CA, DOCKER_*).

## 6. Commands for the five harness agents
```
F=/tmp/claude-0/-home-user/37719b48-fc3a-58ba-bb72-5869c819d794/scratchpad/rebuild/foundation
S=/home/user/harness-interface/data/secrets
cp -r $F/template R/harnesses/<name>; rm R/harnesses/<name>/standin.py   # then edit
python3 $F/hirun.py check   R/harnesses/<name>
python3 $F/hirun.py install R/harnesses/<name> [--local]      # log: $F/tools/<name>-<hash>.install.log
python3 $F/hirun.py run R/harnesses/<name> --local --task "…" --model claude-sonnet-4-6 --key-file $S/ANTHROPIC_API_KEY
python3 $F/hirun.py run R/harnesses/<name> --task "…" --model claude-sonnet-4-6 --key-file $S/ANTHROPIC_API_KEY  # docker, gateway
   [--secret file]  [--instructions "…"]  [--workspace DIR --resume ID]  [--timeout S]  [--quiet]
   [--steer-after-lines N "text"]  [--stop-after-lines N]  [--kill-after-lines N]
   OpenAI:   --provider-url https://api.openai.com --provider-api openai-responses --key-file $S/OPENAI_API_KEY
   DeepSeek: --provider-url https://api.deepseek.com/anthropic --provider-api anthropic-messages --key-file $S/DEEPSEEK_API_KEY
python3 $F/hirun.py clean            # after a crash: hi-* containers, networks, /dev/shm/hi-*
```
Tips: `npm i -g --prefix "$HI_TOOLS" pkg@x.y.z` (egress registry.npmjs.org); `UV_TOOL_DIR=$HI_TOOLS/uv
UV_TOOL_BIN_DIR=$HI_TOOLS/bin uv tool install 'pkg[extra]==x.y.z'` (pypi.org, files.pythonhosted.org);
GitHub releases need github.com + the asset host (the install log ends with the door's allow/deny lines).
Run logs: `<logs>/{stdout.log,stderr.log,output.json,result.json}`. Leak check: `grep -rqF -f $S/<KEY> <dir> && echo LEAK`.

## 7. Known limits; what I'd change in the real execution layer
- The gateway is HTTP/1.1, one request per connection (`Connection: close`, a TLS handshake per call,
  ~0.1–0.2 s), no WebSocket upgrade, auth header by shape only (a provider wanting another header, or
  a CLI that ignores base URLs or refuses `http://`, must use `--secret file`). Not yet tried with
  the five real CLIs: stage 2 should run each with both `gateway` and `file`.
- Threads in hirun; the real layer should be asyncio on `ProcessExecution` (stop = SIGINT + timer,
  as here). One door container per session costs ~1 s; a per-session network is the isolation unit,
  so keep it, but start the door with the network in parallel with workspace prep.
- `responded`/`continued` session logic (stop, then resume with the text) is the server's: hirun only
  offers stop + `--resume`. `metadata` is always `{}`. Request `files` are not exposed by hirun.
- Local mode runs as the runner's user (root here) with the host proxy: development only. `chown -R`
  of the workspace per response is O(files).
- Only install.sh is hashed: a folder copying unpinned files from itself at install time gets a stale cache.
