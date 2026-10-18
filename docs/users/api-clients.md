# Call the API from code

Everything `hi` does is an HTTP call, so any language can drive harness-interface. The request
and response follow the OpenAI Responses wire format, which means the OpenAI SDK works as a
client too. The server listens on `http://127.0.0.1:8000` by default.

## curl

Run a harness and wait for the finished record:

```bash
curl -s localhost:8000/responses -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Write a haiku about a hermit crab."}'
```

Stream it instead, as server-sent events:

```bash
curl -N localhost:8000/responses -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Write a haiku about a hermit crab.", "stream": true}'
```

Continue the conversation by naming the response to continue from:

```bash
curl -s localhost:8000/responses -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Now give it a title.", "previous_response_id": "resp_…"}'
```

## The OpenAI SDK

Point the SDK at the server. The `model` is the harness's name, and the key is unused, since the
server holds the provider keys.

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000", api_key="unused")

first = client.responses.create(model="claude-code", input="Write a haiku about a hermit crab.")
print(first.output_text)

second = client.responses.create(model="claude-code", input="Now give it a title.",
                                 previous_response_id=first.id)
print(second.output_text)

for event in client.responses.create(model="claude-code", input="Count to five.", stream=True):
    print(event.type)        # response.created, harness.output …, response.completed
```

`responses.retrieve(id)` works as well.

### An agent on a harness

A coding harness already does the hard part of an agent: the tool loop, running commands,
editing files, managing its context, resuming its sessions. So an agent can be just a role and a
conversation, with a harness doing the work. `instructions` gives the harness the role, and
`previous_response_id` keeps the conversation:

```python
class Pip:
    """A bakery's assistant. The harness behind it is one name: swap it for any other."""
    harness = "claude-code"
    role = "You are Pip, a bakery's assistant. Answer in French, in one sentence, and sign with -- Pip."

    def __init__(self):
        self.last = None                                  # the conversation so far

    def ask(self, text: str) -> str:
        reply = client.responses.create(model=self.harness, instructions=self.role, input=text,
                                        previous_response_id=self.last)
        self.last = reply.id
        return reply.output_text


pip = Pip()
pip.ask("Which bread keeps longest, and why?")   # "Le pain de seigle se conserve le plus longtemps … -- Pip"
pip.ask("And which one did you just name?")      # "Je viens de nommer le pain de seigle. -- Pip"
```

- **Swap the harness, keep the agent.** Set `harness = "codex"`, or any shipped harness, or one
  you wrote, and nothing else changes. Every shipped harness hands the role to its CLI on every
  turn ([how each one does](../../harnesses/README.md#notes-worth-knowing)).
- **It works in a sandbox.** Whatever the harness does for your agent, it does in a container
  that can reach only its provider.
- **Its work is on the record.** Every turn's answer, changed files, diff, cost and output can be
  read back. To cancel, or to read a run's output, log and files, call those endpoints directly,
  as shown below.

## Python, without an SDK

With [httpx](https://www.python-httpx.org/), streaming and reading the events yourself:

```python
import json
import httpx

with httpx.stream("POST", "http://127.0.0.1:8000/responses", timeout=None,
                  json={"model": "claude-code", "input": "Write a haiku.", "stream": True}) as r:
    r.raise_for_status()
    event = None
    for line in r.iter_lines():
        if line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
            if event == "harness.output":
                print(data["line"])                          # the harness's own output, line by line
            elif event == "response.completed":
                record = data["response"]
                print(record["status"], record["harness"]["session_id"])
```

## The stream

A streamed response is four kinds of event:

| Event | Data |
|---|---|
| `response.created` | `{"type": …, "response": <the record, in_progress>}`, sent at once |
| `harness.output` | `{"type": …, "line": "<one line the harness printed on stdout>"}`, as each line arrives |
| `harness.log` | `{"type": …, "line": "<one line on stderr>"}`, the same way |
| `response.completed` | `{"type": …, "response": <the finished record>}` |

The `X-Response-Id` header carries the response id from the start. A client that disconnects
only stops following: the run finishes and is recorded, and `GET /responses/{id}` has the result.

## After the run

| | |
|---|---|
| `GET /responses/{id}` | the record: status, answer, usage, cost, produced files, session |
| `GET /responses/{id}/output` | the harness's stdout, byte for byte |
| `GET /responses/{id}/log` | its stderr |
| `GET /responses/{id}/diff` | what the run changed, as a diff; live while it runs |
| `GET /responses/{id}/files` | every file in the workspace, as the run left them; while it runs, as they are now |
| `GET /responses/{id}/files/{path}` | one file, as the run left it |
| `POST /responses/{id}/cancel` | stop it: `{"cancelled": true}` if it was running |

## Errors to handle

| Status | Means | Do |
|---|---|---|
| 400 | the request can't run: an unknown harness, a missing provider, a follow-up on another harness | fix the request; `detail` says what |
| 404 | no response with that id, or nothing of that kind for it | check the id |
| 409 | that conversation already has a run in progress | wait for it, or cancel it, then send again |
| 422 | the body isn't a valid request, e.g. no input text | fix the body |

A run that fails is not an HTTP error: the request was fine. The record ends `failed`, with an
`error.code` saying why. Every field is in the [HTTP API reference](api.md).
