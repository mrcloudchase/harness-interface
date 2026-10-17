# Walkthrough

From an empty server to a resumed conversation. Four PUTs, one POST, all over the API.

## 1. Install

The server needs Python 3.11, git, and Docker. gVisor is optional: when `runsc` is registered as
a Docker runtime, every sandbox uses it.

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
pip install -e .
hi serve                   # http://127.0.0.1:8000, state under ./data (HI_DATA_DIR to move it)
```

It starts with no providers, no harnesses, and one sandbox, `default`. Keep the port on
localhost: there is no authentication, and provider keys pass through this process.

Without Docker, `hi serve --runtime local` runs harnesses as plain processes on the host, which
is fine for trying things and for development. Every record then says `runtime: local`, and
there is no isolation and no egress rule.

Everything below is `curl`. Any HTTP client works the same way.

## 2. Add a provider

A provider is where model calls go and the key that unlocks them. The server stores both and
passes them to the harness; it never interprets them.

```bash
curl -X PUT localhost:8000/providers/anthropic -H 'content-type: application/json' \
  -d '{"name":"anthropic","url":"https://api.anthropic.com","key":"sk-ant-..."}'
```

Add as many as you like. DeepSeek serves the Anthropic Messages shape at its own path, so this is
a second provider that Claude Code can run on:

```bash
curl -X PUT localhost:8000/providers/deepseek -H 'content-type: application/json' \
  -d '{"name":"deepseek","url":"https://api.deepseek.com/anthropic","key":"sk-..."}'
```

`GET /providers` lists names and urls. The key is never returned.

## 3. Add a sandbox, or keep the default

A sandbox is a Dockerfile, and it is where a harness runs. `default` is built in: Node and
Python with Claude Code, Codex and DeepSeek Harness installed, run as an unprivileged user. You
do not need to add one to get started.

What locks a sandbox down is not the Dockerfile but what every run gets: all capabilities
dropped, no privilege escalation, a read-only root, tmpfs `/tmp`, pid and memory caps, and a
private internal network whose only exit is the egress door, a tunnel to the harness's provider
host and nothing else. gVisor when the host has it.

Add a sandbox when a harness needs more: a tool, a language, or a host to reach. The provider's
host is always allowed; `egress` adds to it.

```bash
curl -X PUT localhost:8000/sandboxes/python-dev -H 'content-type: application/json' -d '{
  "name": "python-dev",
  "dockerfile": "FROM node:22-bookworm-slim\nRUN apt-get update && apt-get install -y git python3 python3-pip && npm install -g @anthropic-ai/claude-code && useradd -m -u 1000 agent\nUSER 1000\nENV HOME=/workspace/.home\nWORKDIR /workspace\n",
  "egress": ["pypi.org", "files.pythonhosted.org"]
}'
```

The image is built the first time a response needs it and reused after. Change the Dockerfile
and the next response builds the new one. `GET /sandboxes/default` shows the built-in one in full.

## 4. Add a harness

A harness is one CLI, described completely: its command, the files it wants in the workspace,
its scripts, and by name the provider it calls and the sandbox it runs in. Write it as a folder of
three files and `hi pack` turns the folder into the JSON the PUT takes.

The server promises every harness the same thing inside its sandbox. The request arrives on
stdin and in `HI_TASK`, `HI_MODEL`, `HI_SESSION_ID`; the provider as `HI_PROVIDER_URL` and
`HI_PROVIDER_KEY`; `HI_WORKSPACE`, `HI_HARNESS_DIR`, `HI_OUTPUT`. The harness prints whatever it
likes to stdout, which becomes the response's output, and may write `status`, `session_id`,
`usage`, `answer` and `cost_usd` to the file at `HI_OUTPUT`. Files it changes in the workspace
are the produced files.

Here is Claude Code, complete.

`claude-code/harness.yaml`:

```yaml
name: claude-code
description: Claude Code, headless. Speaks the Anthropic Messages API.
provider: anthropic
sandbox: default
files:
  AGENTS.md: "{instructions}"            # the request's instructions, where this CLI reads them
run:
  env:
    HOME: "{workspace}/.home"            # transcripts land inside the workspace, so --resume works later
    IS_SANDBOX: "1"                      # claude refuses --dangerously-skip-permissions as root without this
  stdout: application/x-ndjson
  timeout_s: 900
```

`claude-code/run.sh`, where everything specific to this CLI lives:

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

`claude-code/report.py`, a filter that passes every line through and writes what the server reads:

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

Register it:

```bash
curl -X PUT localhost:8000/harnesses/claude-code -H 'content-type: application/json' \
  -d "$(hi pack claude-code)"
```

That is the whole of adding a harness. Nothing on the server changed, and nothing on the server
knows what `ANTHROPIC_BASE_URL` means.

To run the same CLI on DeepSeek, change one word, `provider: deepseek`, and register it under
another name, or edit this one. The run script already maps whatever provider it is given.

Other CLIs differ only in the lines that are about them. Codex speaks the Responses API, so its
run script exports `OPENAI_BASE_URL` from `HI_PROVIDER_URL`, logs the key in with
`codex login --with-api-key`, runs `codex exec --json` or `codex exec resume --last` when
`HI_SESSION_ID` is set, and its reporter reads `thread.started`, `item.completed` and
`turn.completed`. DeepSeek Harness exports `DEEPSEEK_BASE_URL` and `DEEPSEEK_API_KEY`, runs
`dsh --profile headless --json` with `--session-id` on a follow-up, and its reporter sums the
usage over `status` events. A CLI with no JSON mode at all gets a reporter that picks the answer
out of its text and declares `stdout: text/plain`.

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

`model` names the harness. `claude-code/claude-opus-5-5` would also pass a model through, as
`HI_MODEL`, for the run script to put on the CLI's model flag. On DeepSeek that is
`claude-code-deepseek/deepseek-chat`.

The response is server-sent events. `response.created` comes first with the record in progress.
Then one `harness.output` event per line of Claude Code's own stream-json, exactly as the CLI
printed it, until it exits. Then `response.completed` with the finished record. Leave `stream`
out and the whole record comes back as one JSON object when the run is done.

The record:

```json
{"id": "resp_…", "object": "response", "status": "completed", "model": "claude-code",
 "output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Fixed. …"}]}],
 "usage": {"input_tokens": 2, "output_tokens": 312, "cache_read_input_tokens": 35438},
 "previous_response_id": null, "metadata": {},
 "harness": {"name": "claude-code", "provider": "anthropic", "sandbox": "default", "runtime": "docker",
             "image": "hi/default:3f9c…", "session_id": "babde362-…", "exit_code": 0,
             "latency_s": 10.2, "cost_usd": 0.14, "files": ["prices.py"], "workspace": "…"}}
```

`status` is `completed`, `failed`, `incomplete` on timeout, or `cancelled`. `output` holds the
answer the harness reported. `usage` is whatever the harness reported, in its own names. Under
`harness` is everything the Responses shape has no field for, including which sandbox image the
run happened in.

## 6. Read what happened

```bash
curl localhost:8000/responses/resp_…              # the record
curl localhost:8000/responses/resp_…/output       # the CLI's stdout, byte for byte
curl localhost:8000/responses/resp_…/log          # its stderr, where a CLI explains a failure
curl localhost:8000/responses/resp_…/files/prices.py
curl localhost:8000/responses                     # every record
curl -X POST localhost:8000/responses/resp_…/cancel
```

## 7. Continue

A conversation is a chain of responses. Name the one to continue from:

```bash
curl localhost:8000/responses -H 'content-type: application/json' -d '{
  "model": "claude-code",
  "input": "Now add a count() function and say what you changed earlier.",
  "previous_response_id": "resp_…"
}'
```

The same workspace is reused with the files as the harness left them, and the CLI is relaunched
with the session id it reported, so it remembers the earlier turn. A response can only continue
one made on the same harness. Leave `previous_response_id` out to start fresh.

That is the loop: add resources once, post tasks, read records, continue or start over.
