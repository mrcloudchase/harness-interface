# Harness folder template (contract 1)

Copy this folder to start a harness: `cp -r harnesses/template harnesses/<name>`, then replace
`install.sh`, `run.sh`, `adapter.py`, `home/` and `workspace/`, and delete `standin.py`. Keep
`hi_adapter.py` byte-identical to `harness_interface/harness/hi_adapter.py`: the server refuses a
folder whose copy differs.

```
<name>/
  harness.json      what the server needs to know (below); an unknown or missing field is an error
  install.sh        installs the pinned CLI into $HI_TOOLS (executables in $HI_TOOLS/bin)
  run.sh            maps HI_* onto the CLI's own settings, then `exec python3 -u adapter.py`
  adapter.py        drives the CLI: subclass hi_adapter.Adapter (start, on_line, steer, stop)
  hi_adapter.py     the shared plumbing, identical in every folder
  home/             config artifacts: copied into $HOME before every response
  workspace/        work artifacts: copied into the workspace when a session starts
  image.Dockerfile  optional: `FROM hi-base` plus the OS packages install.sh can't add
  standin.py        template only: the fake CLI (counts with sleeps, steers, aborts, resumes, remembers)
```

## harness.json

| field | meaning |
|---|---|
| `contract` | `1`, the contract this folder was written for |
| `name` | `[a-z0-9-]+`; names the tools directory |
| `description` | one line |
| `provider` | the default provider `{url, api}`; `api` is one of `apis`; `url` is the base URL the shape's official SDK takes: `anthropic-messages` without `/v1` (`https://api.anthropic.com`), `openai-*` with the version path (`https://api.openai.com/v1`) |
| `apis` | the shapes the harness speaks: `anthropic-messages`, `openai-responses`, `openai-chat` |
| `install` | `egress` (the hosts install.sh may reach) and `timeout_s` |
| `files` | `{workspace path: template}`, rendered before every response; `{instructions}` is the request's instructions; an empty render deletes the file. Target the CLI's user-level file under `.home/`, never the project's own |
| `run.interrupt` | `steered` (later stdin lines reach the running work), `continued` (stop, then resume with the text) or `responded` |
| `run.stdout` | the content type of stdout, e.g. `application/x-ndjson` |
| `run.timeout_s`, `run.stop_timeout_s` | the response's limit; the grace between SIGINT and the kill (more than the adapter's `stop_grace_s`) |
| `run.credential` | optional: `gateway` (the default: the key file holds a session token the gateway swaps for the key) or `file` (it holds the key) |
| `run.egress` | optional: hosts a session may reach beyond its provider; none by default |
| `report` | optional: globs under `$HOME` (`*`, `?`, `**`) of artifacts the harness writes that come back with each response |

## What a harness is given

`HI_WORKSPACE` (the working directory, the same path inside and outside the sandbox), `HOME`
(`$HI_WORKSPACE/.home`, kept between responses), `HI_HARNESS_DIR` (this folder, read-only),
`HI_OUTPUT` (the result file, outside the workspace), `HI_PROVIDER_URL`, `HI_PROVIDER_API`,
`HI_PROVIDER_KEY_FILE` (when there is a provider), `HI_MODEL` (or empty), `PATH` (`$HI_TOOLS/bin`
first), and in the sandbox `HTTPS_PROXY` and `NO_PROXY`. Nothing else.

stdin line 1 is `{"task": "…", "resume": "…" or null}`; for `steered` harnesses each later line is
one JSON string. stdin stays open: its end means stop gracefully, and so does SIGINT; a kill follows
`run.stop_timeout_s` later.

## What it gives back

stdout and stderr, streamed and kept as they are; the workspace's changes; the `report` artifacts
that changed; and `$HI_OUTPUT`: `{answer, status, resume, usage, cost_usd, steers}` plus any key
of your own, written early (`status: running` with `resume`, as soon as it is known) and at the end.
`status` is `running`, `ok`, `fail` or `stopped`, from the CLI's events, never its exit code;
`steers` counts the steer lines the CLI took; `usage` uses `input_tokens`, `output_tokens`,
`cache_read_tokens`, `cache_write_tokens` and `reasoning_tokens`.
