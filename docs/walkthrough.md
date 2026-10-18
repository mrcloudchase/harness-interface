# Walkthrough

From an empty server to a resumed conversation, then your own harness. Each step shows the `hi`
command first, then the HTTP call it makes. The API is the product; `hi` is one client of it.

Before you start, install and start the server ([setup.md](setup.md)):

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
hi server start
```

Nothing below needs a restart: every change takes effect on the next request.

## 1. Add a provider

A provider is where model calls go, and the key that unlocks them. The server stores both and
hands them to the harness. It never interprets either one.

```bash
hi provider add anthropic --url https://api.anthropic.com --key-env ANTHROPIC_API_KEY
```

```bash
curl -X PUT localhost:8000/providers/anthropic -H 'content-type: application/json' \
  -d '{"name":"anthropic","url":"https://api.anthropic.com","key":"sk-ant-..."}'
```

Add as many as you like. DeepSeek serves the Anthropic Messages shape at its own path, so this
second provider can run Claude Code too:

```bash
hi provider add deepseek --url https://api.deepseek.com/anthropic --key-env DEEPSEEK_API_KEY
```

`hi provider ls` (or `GET /providers`) lists names and urls. A key is never returned.

## 2. Keep the default sandbox, or add one

A sandbox is a Dockerfile, and it is where a harness runs. The built-in `default` holds the CLI
of every shipped harness, and runs as an unprivileged user, uid 1000. You don't need another
sandbox to get started.

The Dockerfile is not what locks a run down. Every run gets the same hardening, whatever its
sandbox ([architecture.md](architecture.md#the-sandbox)):
- every capability dropped;
- a read-only root;
- a private network whose only way out is a tunnel to its provider.

Add a sandbox when a harness needs something more: a tool, a language, or another host to
reach. The provider's host is always allowed, and `egress` adds to it. The image needs a user
with uid 1000, because that user owns the workspace.

```dockerfile
# python-dev.Dockerfile
FROM python:3.12-slim
RUN useradd -m -u 1000 runner
USER runner
ENV HOME=/workspace/.home
WORKDIR /workspace
```

```bash
hi sandbox add python-dev python-dev.Dockerfile --egress pypi.org files.pythonhosted.org
```

```bash
curl -X PUT localhost:8000/sandboxes/python-dev -H 'content-type: application/json' -d '{
  "name": "python-dev",
  "dockerfile": "FROM python:3.12-slim\nRUN useradd -m -u 1000 runner\nUSER runner\nENV HOME=/workspace/.home\nWORKDIR /workspace\n",
  "egress": ["pypi.org", "files.pythonhosted.org"]
}'
```

## 3. Add a harness

```bash
hi harness add --builtin claude-code
```

A harness is a folder: a `harness.json`, plus the scripts it runs. `hi` turns the folder into
the PUT body, which is `harness.json` with every other file under `scripts`:

```bash
harness() {
  jq --argjson scripts "$(for f in "$1"/*; do [ "${f##*/}" = harness.json ] || jq -n --arg k "${f##*/}" --rawfile v "$f" '{($k): $v}'; done | jq -s add)" \
     '. + {scripts: $scripts}' "$1/harness.json"
}
harness harnesses/claude-code | curl -X PUT localhost:8000/harnesses/claude-code -H 'content-type: application/json' -d @-
```

What is in [harnesses/claude-code/](../harnesses/claude-code/):

**`harness.json`** says how the CLI runs:

```json
{
  "name": "claude-code",
  "provider": "anthropic",
  "files": {"AGENTS.md": "{instructions}"},
  "run": {
    "env": {"HOME": "{workspace}/.home", "IS_SANDBOX": "1"},
    "stdout": "application/x-ndjson",
    "timeout_s": 900
  }
}
```

- `files` are written into the workspace before each run. Here, the request's instructions go
  where Claude Code reads them.
- `HOME` is inside the workspace, so the CLI's transcripts are still there on the next turn.
- `sandbox` is left out, so the harness runs in `default`.
- `run.argv` is left out, so the command is `bash {harness_dir}/run.sh`.

**`run.sh`** maps the request onto the CLI. Everything specific to Claude Code lives here:

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

**`report.py`** passes every line through, and writes what the server reads back: the session
to resume, the status, usage, cost and the answer.

Nothing on the server knows what `ANTHROPIC_BASE_URL` means. To run the same CLI on DeepSeek,
set `"provider": "deepseek"` and add it again; the run script maps whatever provider it is
given.

## 4. Run it

```bash
hi run claude-code "The tests are failing. Find out why and fix it." \
  -f prices.py -f test_prices.py -i "Keep changes minimal. Do not edit test files."
```

While it runs, `hi` shows Claude Code's own output on stderr. When it finishes, it prints the
answer on stdout, plus a summary line: status, time, cost, produced files, and the response id.

The same request over HTTP, streamed:

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

- `model` names the harness. `claude-code/claude-opus-5-5` also picks the CLI's model.
- With `"stream": true`, the response is server-sent events:
  1. `response.created`, at once;
  2. one `harness.output` event for each line the CLI prints;
  3. `response.completed`, carrying the finished record.
- Without `stream`, the finished record comes back as one JSON object.

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

The run belongs to the server, not to your connection. Close the terminal or drop the stream,
and the harness keeps going; its record, output and log are there when it finishes.

## 5. Read what happened

| `hi` | HTTP | |
|---|---|---|
| `hi show ID` | `GET /responses/ID` | the record |
| `hi output ID` | `GET /responses/ID/output` | the harness's stdout, byte for byte |
| `hi log ID` | `GET /responses/ID/log` | its stderr, where a CLI explains a failure |
| `hi files ID prices.py` | `GET /responses/ID/files/prices.py` | a file from its workspace |
| `hi ls` | `GET /responses` | every record |

## 6. Continue the conversation

```bash
hi run claude-code "Now add a count() function, and say what you changed earlier." -c
```

```bash
curl localhost:8000/responses -H 'content-type: application/json' -d '{
  "model": "claude-code",
  "input": "Now add a count() function, and say what you changed earlier.",
  "previous_response_id": "resp_…"
}'
```

- `-c` continues the last response; `-c ID` continues a particular one.
- The run reuses the conversation's workspace, with the files as the harness left them.
- The CLI gets the session id it reported as `HI_SESSION_ID`, so it remembers the earlier turn.
- A conversation stays on its harness, and runs one request at a time. A follow-up sent while the
  previous one still runs gets a 409.

## 7. Cancel

Press Ctrl-C during `hi run`, or run `hi cancel ID` (`POST /responses/ID/cancel`).
- If the sandbox is still being built, the harness never starts.
- If the harness is running, it is killed.

Either way, the record ends `cancelled`. To start a run and leave it going, use
`hi run … --detach`.

## 8. Write your own harness

Any program that can take a task can be a harness. The smallest one is a folder with two files.

**`hello/harness.json`**:

```json
{"name": "hello", "provider": "anthropic", "run": {"stdout": "text/plain"}}
```

**`hello/run.sh`**:

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "asked: $HI_TASK"                                       # stdout streams back as the output
echo "$HI_TASK" >> notes.txt                                 # a produced file, kept in the workspace
printf '{"status":"ok","session_id":"notes","answer":"%s notes so far"}' \
  "$(wc -l < notes.txt)" > "$HI_OUTPUT"                      # what the record reports
```

```bash
hi harness add ./hello
hi run hello "first"          # → 1 notes so far
hi run hello "second" -c      # → 2 notes so far: the same workspace, session "notes"
```

That's the whole contract:
- **In:** the task as `HI_TASK`, the model, the session to resume, and the provider's url and key.
- **Out:** stdout, stderr, and an optional `HI_OUTPUT` file.

A real harness puts its CLI where `echo` is, and maps the provider onto the CLI's variables. The
contract in full is in [api.md](api.md#the-harness-contract), and the 23 shipped harnesses in
[harnesses/](../harnesses/) are working examples.
