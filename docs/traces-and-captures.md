# Traces and captures

Two records of a session: what the member sent and got back, and what the agent said to its
provider.

## The trace

```bash
curl -s https://hg.example.com/v1/sessions/sess_…/trace -H "Authorization: Bearer $KEY"
```

One line per event, in order, each with the time, the kind and the response it concerns:

| Kind | Body |
|---|---|
| `request` | the request as sent, every field, with files replaced by their names and sizes |
| `interrupt` | the steer's text |
| `cancel` | nothing |
| `response` | the whole response record as it ended, with the raw streams |

The trace is the member's record of the session and the deployer never reads it.

## Captures

```bash
curl -s https://hg.example.com/v1/responses/resp_…/captures -H "Authorization: Bearer $KEY"
curl -s https://hg.example.com/v1/responses/resp_…/captures/provider/0001.json -H "Authorization: Bearer $KEY"
```

Every call the sandbox made to its provider during the turn, as the gateway relayed it, numbered
in order: the time, method, path, status, and the request and response bodies up to four
megabytes each. The key the gateway added is not in it. `door.log` is the door's decisions during
the turn: each host allowed or denied, each forward to the gateway.

```json
{"at": 1792713210.5, "method": "POST", "path": "/anthropic/v1/messages", "status": "200",
 "request": "{\"model\":\"deepseek-chat\",\"messages\":[…],\"tools\":[…]}",
 "response": "event: message_start\ndata: {…}\n\n…"}
```

This is the complete record of what the agent saw and said: the system prompt the CLI built, the
tools it declared, every message and tool result, and the model's answers. It is the data a
harness is made of.

## Usage

The gateway counts each relayed call and its bytes in and out, and the worker records the
seconds a turn ran. The deployer sees these as totals per tenant, which is all the deployer sees
of a tenant's work.

Next: [Members and keys](members-and-keys.md).
