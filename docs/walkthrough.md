# Walkthrough

From an empty server to a resumed conversation: one provider, one harness, two requests, all
over the API with `curl`. Every step here is also a `hi` command; see [cli.md](cli.md).

## 1. Install and start

You need git, and Docker for sandboxed runs. The installer brings uv, Python, the server and
`hi`:

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
hi server start                  # or run `harness-interface` in the foreground
```

The server listens on `http://127.0.0.1:8000`. It starts with no providers and no harnesses,
plus one built-in sandbox, `default`. Everything it stores lives under
`~/.harness-interface/data`. From a clone of the repository, `uv run harness-interface` starts
it straight from the source.

The environment configures it:

| Variable | Default | |
|---|---|---|
| `HI_HOST` | `127.0.0.1` | the address to listen on |
| `HI_PORT` | `8000` | the port |
| `HI_DATA_DIR` | `~/.harness-interface/data` | resources, records, logs and workspaces |
| `HI_RUNTIME` | `docker` | `docker`, or `local` to run harnesses as plain processes on the host |

Keep it on localhost. There is no authentication, and provider keys pass through this process.

With the default `docker` runtime, the server checks at startup that Docker is reachable and
will not start without it. `HI_RUNTIME=local hi server start` needs no Docker. Use it to try
things out or to develop a harness. A local run has no isolation and no egress rule, and its record says
`"runtime": "local"`.

The server also needs git, because every workspace is a git repository, and it won't start
without git either.

Everything below is `curl`, plus `jq` to turn a harness folder into JSON. Nothing needs a
restart: every PUT takes effect on the next request.

## 2. Add a provider

A provider is where model calls go and the key that unlocks them. The server stores both and
hands them to the harness. It never interprets either one.

```bash
curl -X PUT localhost:8000/providers/anthropic -H 'content-type: application/json' \
  -d '{"name":"anthropic","url":"https://api.anthropic.com","key":"sk-ant-..."}'
```

Add as many as you like. DeepSeek serves the Anthropic Messages shape at its own path, so this
second provider runs Claude Code too:

```bash
curl -X PUT localhost:8000/providers/deepseek -H 'content-type: application/json' \
  -d '{"name":"deepseek","url":"https://api.deepseek.com/anthropic","key":"sk-..."}'
```

`GET /providers` lists names and urls. A key is never returned.

## 3. Keep the default sandbox, or add one

A sandbox is a Dockerfile, and it is where a harness runs. The built-in `default` is one image
holding the CLI of every harness in [harnesses/](../harnesses/), run as an unprivileged user,
uid 1000. You don't need to add a sandbox to get started.

The first request that needs an image builds it. For `default` that takes several minutes and
about 10 GB of disk. Every request after that reuses the image, and each run is a fresh container
from it. `GET /sandboxes/default` shows its Dockerfile.

The Dockerfile is not what locks a sandbox down. Every run gets the same hardening:
- every capability dropped, and no privilege escalation;
- a read-only root, and pid and memory caps;
- a private network whose only way out is the egress door, a tunnel to the harness's provider host.

Add a sandbox when a harness needs something more: a tool, a language, or another host to reach.
The provider's host is always allowed, and `egress` adds to it. The image needs a user with uid
1000, because that user owns the workspace:

```bash
curl -X PUT localhost:8000/sandboxes/python-dev -H 'content-type: application/json' -d '{
  "name": "python-dev",
  "dockerfile": "FROM python:3.12-slim\nRUN useradd -m -u 1000 runner\nUSER runner\nENV HOME=/workspace/.home\nWORKDIR /workspace\n",
  "egress": ["pypi.org", "files.pythonhosted.org"]
}'
```

Change the Dockerfile and the next request builds and uses the new image.

## 4. Add a harness

A harness describes one CLI completely:
- its command;
- the files it wants in the workspace;
- its scripts;
- by name, the provider it calls and the sandbox it runs in.

It is written as a folder: a `harness.json` and the scripts it runs.

The server promises every harness the same inputs inside its sandbox:
- The request arrives as JSON on stdin and at `HI_REQUEST`.
- The task, model and session to resume arrive as `HI_TASK`, `HI_MODEL` and `HI_SESSION_ID`.
- The provider arrives as `HI_PROVIDER_URL` and `HI_PROVIDER_KEY`.
- `HI_WORKSPACE` and `HI_HARNESS_DIR` say where its workspace and scripts are.

The harness gives back:
- stdout, which becomes the response's output;
- stderr, which becomes the log;
- optionally, `status`, `session_id`, `usage`, `answer` and `cost_usd`, written as JSON to the file at `HI_OUTPUT`.

Files it adds or changes in the workspace are the response's produced files.

Here is Claude Code, from [harnesses/claude-code/](../harnesses/claude-code/).

`harness.json`:

```json
{
  "name": "claude-code",
  "description": "Claude Code, headless. ...",
  "provider": "anthropic",
  "files": {"AGENTS.md": "{instructions}"},
  "run": {
    "env": {"HOME": "{workspace}/.home", "IS_SANDBOX": "1"},
    "stdout": "application/x-ndjson",
    "timeout_s": 900
  }
}
```

The fields:
- `files` are written into the workspace before each run. Here that is the request's instructions, where Claude Code reads them.
- `HOME` is inside the workspace, so the CLI's transcripts are still there on the next turn.
- `IS_SANDBOX` lets Claude Code skip its permission prompts.
- `sandbox` is left out, so it runs in `default`.
- `run.argv` is left out, so the command is `bash {harness_dir}/run.sh`.

`run.sh` is where everything specific to this CLI lives:

```bash
#!/usr/bin/env bash
set -euo pipefail
# The CLI appends /v1/messages itself, so the provider URL must not end in /v1.
base="${HI_PROVIDER_URL%/}"
export ANTHROPIC_BASE_URL="${base%/v1}" ANTHROPIC_API_KEY="$HI_PROVIDER_KEY" ANTHROPIC_AUTH_TOKEN="$HI_PROVIDER_KEY"
claude -p "$HI_TASK" --output-format stream-json --verbose --dangerously-skip-permissions \
  ${HI_MODEL:+--model "$HI_MODEL"} ${HI_SESSION_ID:+--resume "$HI_SESSION_ID"} \
  | python3 "$HI_HARNESS_DIR/report.py"
```

`report.py` passes every line through and writes what the server reads:

```python
import json, os, sys

out = {}
for line in sys.stdin:
    sys.stdout.write(line)
    sys.stdout.flush()
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "system" and ev.get("session_id"):
        out["session_id"] = ev["session_id"]
    if ev.get("type") == "result":
        out["status"] = "fail" if ev.get("is_error") else "ok"
        out["usage"] = ev.get("usage")
        out["cost_usd"] = ev.get("total_cost_usd")
        out["answer"] = ev.get("result") or ""
json.dump(out, open(os.environ["HI_OUTPUT"], "w"))
```

Register it. The PUT body is `harness.json` plus a `scripts` object holding every other file in the folder:

```bash
harness() {
  jq --argjson scripts "$(for f in "$1"/*; do [ "${f##*/}" = harness.json ] || jq -n --arg k "${f##*/}" --rawfile v "$f" '{($k): $v}'; done | jq -s add)" \
     '. + {scripts: $scripts}' "$1/harness.json"
}
harness harnesses/claude-code | curl -X PUT localhost:8000/harnesses/claude-code -H 'content-type: application/json' -d @-
```

The same function registers all 23 in a loop; see [harnesses/README.md](../harnesses/README.md).

That is all it takes to add a harness. Nothing changed on the server, and nothing on the server
knows what `ANTHROPIC_BASE_URL` means. To run the same CLI on DeepSeek, set
`"provider": "deepseek"` and register it again, under this name or another. The run script maps
whatever provider it is given.

Other CLIs differ only in the lines that are about them:
- **Codex** speaks the Responses API. Its run script exports `OPENAI_BASE_URL`, logs the key in, and runs `codex exec --json`, or `codex exec resume` on a follow-up.
- **Cline** resumes only through its Agent Client Protocol mode, so its folder carries a small ACP client.
- **A CLI with no JSON mode** gets a `report.py` that picks the answer out of its text, and declares `"stdout": "text/plain"`.

## 5. Make the first request

```bash
curl -N localhost:8000/responses -H 'content-type: application/json' -d '{
  "model": "claude-code",
  "instructions": "Keep changes minimal. Do not edit test files.",
  "input": [
    {"type": "input_text", "text": "The tests are failing. Find out why and fix it."},
    {"type": "input_file", "filename": "prices.py", "file_data": "..."},
    {"type": "input_file", "filename": "test_prices.py", "file_data": "..."}
  ],
  "stream": true
}'
```

`model` names the harness. `claude-code/claude-opus-5-5` also passes a model through as
`HI_MODEL`, and the run script puts it on the CLI's `--model` flag. Each `input_file` is written
into the workspace before the run.

With `"stream": true` the response comes back as server-sent events:
1. `response.created`, at once, carrying the record while it is in progress;
2. one `harness.output` event for each line Claude Code prints, exactly as printed, until it exits;
3. `response.completed`, carrying the finished record.

Leave `stream` out and the finished record comes back as one JSON object once the run is done.
Either way, the `X-Response-Id` header carries the id.

The run belongs to the server, not to your connection. Close the stream, or lose the connection,
and the harness keeps going; its record, output and log are all there when it is done. Many
clients can run harnesses at once, each request in its own sandbox.

The record:

```json
{"id": "resp_…", "object": "response", "status": "completed", "model": "claude-code",
 "output": [{"type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": "Fixed. …", "annotations": []}]}],
 "usage": {"input_tokens": 2, "output_tokens": 312, "cache_read_input_tokens": 35438},
 "previous_response_id": null, "metadata": {}, "error": null, "incomplete_details": null,
 "harness": {"name": "claude-code", "provider": "anthropic", "sandbox": "default", "runtime": "docker",
             "image": "harness-interface/default:3f9c…", "workspace": "…/data/workspaces/resp_…",
             "session_id": "babde362-…", "exit_code": 0, "latency_s": 10.2, "cost_usd": 0.14,
             "files": ["prices.py"]}}
```

The fields:
- `status` is one of:
  - `completed`;
  - `failed`, with `error`;
  - `incomplete` on timeout, with `incomplete_details`;
  - `cancelled`.
- `output` holds the answer the harness reported.
- `usage` is whatever the harness reported, in its own key names.
- `harness` holds everything the Responses shape has no field for, including the image the run used and the session it can be resumed from.

## 6. Read what happened

```bash
curl localhost:8000/responses/resp_…                   # the record
curl localhost:8000/responses/resp_…/output            # the harness's stdout, byte for byte
curl localhost:8000/responses/resp_…/log               # its stderr, where a CLI explains a failure
curl localhost:8000/responses/resp_…/files/prices.py   # any file in its workspace
curl localhost:8000/responses                          # every record
curl -X POST localhost:8000/responses/resp_…/cancel    # stop a run in progress
```

Cancel works at any point: while the sandbox is still being built the harness never starts, and
once it is running it is killed. The record ends `cancelled`. A run that could not start, because
its sandbox failed to build for example, ends `failed` with `"code": "setup_failed"` and the reason.

## 7. Continue

A conversation is a chain of responses. Name the response to continue from:

```bash
curl localhost:8000/responses -H 'content-type: application/json' -d '{
  "model": "claude-code",
  "input": "Now add a count() function, and say what you changed earlier.",
  "previous_response_id": "resp_…"
}'
```

The run reuses that response's workspace, with the files as the harness left them, and hands the
CLI the session id it reported as `HI_SESSION_ID`, so it remembers the earlier turn. A response
can only continue one made on the same harness, and a conversation has one run at a time: a
follow-up sent while the previous one is still running gets a 409. Leave `previous_response_id`
out to start a new conversation in a new workspace.

That is the whole loop: add resources once, post requests, read the records, continue or start over.
