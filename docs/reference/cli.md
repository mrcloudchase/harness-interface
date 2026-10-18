# CLI reference

`hi` is a client of the API and nothing more. Every command is one API call, or a few, and
`--json` shows exactly what the API answered. The one exception is `hi server`, which starts
and stops the server itself.

`hi` comes with the server: see [Install](../guides/install.md) to install both. To talk to a server
other than `http://127.0.0.1:8000`, set `HI_URL`, or put `--url URL` before the command
(`hi --url URL ls`).

## Server

```bash
hi server start          # in the background; its log is ~/.harness-interface/server.log
hi server status
hi server logs
hi server stop
```

`hi server start` starts the server on the address `hi` talks to, and waits until it answers. If
the server can't start (no Docker, no git), `hi` shows why.

## Set up

```bash
hi provider add anthropic --url https://api.anthropic.com --key-env ANTHROPIC_API_KEY
hi harness add --builtin claude-code      # one shipped harness; --builtin alone adds all 23
hi harness add ./my-harness               # any folder with a harness.json
hi sandbox add python-dev ./Dockerfile --egress pypi.org files.pythonhosted.org
```

`--key-env` reads the key from that environment variable. Without it, `hi` prompts for the key,
or reads it from stdin. A key never appears on the command line. To see or remove resources:

```bash
hi provider ls | show NAME | rm NAME
hi sandbox  ls | show NAME | rm NAME
hi harness  ls | show NAME | rm NAME
```

## Run

```bash
hi run claude-code "Fix the failing test" -f prices.py -f test_prices.py -i "Keep it minimal"
hi run claude-code "Now add a test for it" -c          # continue the last response
hi run claude-code "…" -c resp_…                       # continue a particular one
hi run claude-code/claude-opus-5-5 "…"                 # pick the harness's model
echo "a long task" | hi run codex -                    # the task from stdin
```

While a run is going:
- everything the harness prints, stdout and stderr, streams to your terminal (on stderr);
- when it ends, the answer goes to stdout, so `hi run … > answer.txt` keeps just the answer;
- a summary line goes to stderr: status, time, cost, files changed and deleted, and the response id.

`hi run` exits 0 when the run completed, and 1 otherwise.

| Flag | |
|---|---|
| `-f FILE` | put a file in the workspace; repeat for more |
| `-i TEXT` | instructions, which the harness gets as `{instructions}` |
| `-c [ID]` | continue a conversation: the last response, or the one named |
| `-q` | don't show the harness's output while it runs |
| `--json` | print the finished record instead of the answer |
| `--detach` | print the response id and return; the run carries on in the server |

**Ctrl-C** cancels the run. To leave a run going, use `--detach` from the start. Closing the
terminal also leaves it going, because runs belong to the server, not to `hi`.

## Read

```bash
hi ls                     # every response
hi show ID                # its record
hi output ID              # the harness's stdout, byte for byte
hi log ID                 # its stderr
hi diff ID                # what it changed, as a diff; live while it runs
hi files ID               # every file in its workspace, as it left them
hi files ID PATH          # one of them
hi cancel ID              # stop it
```

## Exit codes

| | |
|---|---|
| `0` | the command worked; for `hi run`, the run completed |
| `1` | it didn't: an API error, no server, or a run that failed, timed out or was cancelled with `hi cancel` |
| `130` | `hi run` was cancelled with Ctrl-C |
