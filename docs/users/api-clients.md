# Call the API from code

The request and response follow the OpenAI Responses wire format, so the OpenAI SDK works as a client,
and anything that speaks HTTP works too. Sessions (follow, interrupt, stop) are plain HTTP routes. The
server listens on `http://127.0.0.1:8000` by default; every field is in the [API reference](api.md).

## curl

```bash
# a new session, the whole response when it ends
curl -s localhost:8000/responses -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Write hello.py that prints hello."}'

# the same, streamed as server-sent events
curl -N localhost:8000/responses -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Write hello.py that prints hello.", "stream": true}'

# continue that session
curl -s localhost:8000/responses -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Now make it print goodbye too.", "previous_response_id": "resp_…"}'
```

## The OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000", api_key="unused")   # the server holds the provider keys

first = client.responses.create(model="claude-code", input="Remember the word ORCHID. Reply OK.")
second = client.responses.create(model="claude-code", input="Which word did I ask you to remember?",
                                 previous_response_id=first.id)
print(second.output_text)                       # ORCHID

for event in client.responses.create(model="codex", input="Count to five.", stream=True):
    print(event.type)                           # response.created, harness.stdout …, response.completed
```

Everything the Responses shape has no field for is under `harness` on each response: the harness's own
stdout and stderr, the diff, the changed files' contents, the file list, the reported artifacts and its
resume handle. With the SDK it's on `response.model_extra["harness"]`.

## Drive a session like an interactive CLI

Start the work streamed, put more text into it while it runs, and stop it, with
[httpx](https://www.python-httpx.org/):

```python
import json, threading, httpx

api = httpx.Client(base_url="http://127.0.0.1:8000", timeout=None)

def events(response):
    name = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            yield name, json.loads(line[6:])

with api.stream("POST", "/responses", json={
        "model": "pi", "stream": True,
        "input": "Write the numbers 1 to 30 to count.txt, one shell command per number, each followed by sleep 1. No loops."}) as r:
    session = r.headers["x-session-id"]
    threading.Timer(8, lambda: api.post(f"/sessions/{session}/interrupt",
                                         json={"input": "Stop counting; write DONE to done.txt instead."})).start()
    for name, data in events(r):
        if name == "harness.stdout":
            print(data["line"])                 # the CLI's own events, as it prints them
        elif name == "harness.steer":
            print(">>", data["input"])          # where the steer landed among them
        elif name == "response.completed":
            print(data["response"]["status"], data["response"]["harness"]["changes"])
```

- **Interrupt** (`POST /sessions/{id}/interrupt`) replies with its outcome: `steered` (the text went
  into the running work), or `continued` / `responded` (the session continued with it in a new response).
- **Stop** (`POST /sessions/{id}/stop`) stops gracefully, kills after the timeout, and says which.
- **Follow** (`GET /sessions/{id}?stream=true`) lets any number of clients watch a session, each from the
  start of what it is running; leaving never stops it.

## Agents and loops

- **An agent without memory** sends each request as a new session: its role in `instructions`, its
  inputs as files.
- **An agent with memory** keeps the last response id per conversation and continues it with
  `previous_response_id`; the CLI's own memory grows in that session.
- **A loop** sends a task, checks the work with something the harness can't argue with (tests, a
  build), and sends back what failed, continuing the session, or starting a fresh one each round with
  the files it wants. Each response's `harness.changes` is the work to apply; `harness.usage` and
  `harness.cost_usd` give a budget; `stop` gives a deadline.

## Errors to handle

| Status | Means | Do |
|---|---|---|
| 400 | it can't be done: an unknown harness, no provider for it, a shape it doesn't speak, a failed install | fix the request; `detail` says what |
| 404 | no such session, response, harness or provider | check the id |
| 409 | that session already has a response running | interrupt it, or wait |
| 422 | the body isn't valid | fix the body |

A harness that fails is not an HTTP error: the response ends `failed`, with `error.code` and its output.
