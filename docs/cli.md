# hi, the command line

`hi` is a client of the API and nothing more. Every command is one API call, or a few, and
`--json` shows exactly what the API answered. The one exception is `hi server`, which starts
and stops the server itself.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
```

You need git and, for sandboxed runs, Docker. The installer brings everything else:
1. It installs [uv](https://docs.astral.sh/uv/) if it is missing.
2. uv installs Python and the package from GitHub.
3. You get two commands: `hi` and `harness-interface`, the server.

To pick a version, set `HI_REF` to a tag, a branch or a commit, e.g.
`curl … | HI_REF=v1.0.0 sh`. To uninstall, run `uv tool uninstall harness-interface`. Your
data in `~/.harness-interface` stays.

## Start

```bash
hi server start          # in the background; its log is ~/.harness-interface/server.log
hi server status
hi server logs
hi server stop
```

The server keeps everything under `~/.harness-interface/data`. It runs every harness in Docker,
and won't start without Docker. To run harnesses directly on this machine instead, with no
sandbox, start it with `HI_RUNTIME=local hi server start`.

`hi` talks to `http://127.0.0.1:8000`. To use another server, set `HI_URL` or pass `--url`;
`hi server start` then starts the server on that address.

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
- the harness's own output streams to stderr;
- when it ends, the answer goes to stdout, so `hi run … > answer.txt` keeps just the answer;
- a summary line goes to stderr: status, time, cost, produced files, and the response id.

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
hi files ID PATH          # a file from its workspace
hi cancel ID              # stop it
```

## From a checkout

Inside a clone of the repository, `uv run hi …` runs the CLI and `uv run harness-interface` runs
the server, both straight from the source.
