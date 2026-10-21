# Getting started

Ten minutes: a server, an org, a provider, a sandbox, a harness and a request. This is the
self-hosted path; a hosted platform differs only in how an org is created
([multi-tenant setup](multi-tenant.md)).

You need Docker running and [uv](https://docs.astral.sh/uv/).

## 1. Install and initialize

```bash
uv tool install "git+https://github.com/mrcloudchase/harness-interface@v3.0.0"
harness-interface init --org acme --owner chase
```

`init` writes a master key to `~/.harness-interface/data/master.key`, creates the org `acme` with
`chase` as its owner, and prints the owner's API key once. Keep it: it is how you register things.

```bash
harness-interface serve
```

The server listens on `127.0.0.1:8000`. Put TLS in front of it before anyone else reaches it.

## 2. Add a provider

A provider is a model endpoint and its key. The key is sealed on arrival and never shown again.

```bash
export HI="http://127.0.0.1:8000" KEY="hi_…"
curl -s -X PUT $HI/v1/providers/anthropic -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.anthropic.com", "api": "anthropic-messages", "key": "sk-ant-…"}'
```

## 3. Add a sandbox

A sandbox is an image with nothing of ours in it, plus the hosts a run may reach besides its
provider, and limits.

```bash
curl -s -X PUT $HI/v1/sandboxes/node22 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"image": "node:22-bookworm-slim", "egress": [], "memory": "4g", "pids": 512}'
```

## 4. Add a harness

A harness is a folder you upload: how to install the CLI, how to run one turn, and the seed files
for its config. Copy the Claude Code example from [the harness template](harness-template.md) into a
directory, then:

```bash
tar czf claude-code.tgz -C claude-code .
curl -s -X PUT $HI/v1/harnesses/claude-code -H "Authorization: Bearer $KEY" --data-binary @claude-code.tgz
```

The server validates the folder, stores it by the digest of its files, and makes it the version
requests run on. The CLI is installed the first time the harness runs in a sandbox, then cached.

## 5. Make a request

Any OpenAI Responses client works. `model` is the harness's name.

```bash
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Create hello.py that prints hello, run it, and say done."}'
```

Or from Python:

```python
from openai import OpenAI
client = OpenAI(api_key="hi_…", base_url="http://127.0.0.1:8000/v1")
r = client.responses.create(model="claude-code", input="Create hello.py that prints hello, run it, and say done.")
print(r.status, r.output_text)
```

The response's `output` is two messages: everything `request.sh` wrote to stdout, then everything
it wrote to stderr. `status` is `completed` when it exited 0. `metadata.session_id` names the
session; send `previous_response_id` to continue it. [Requests](requests.md) has the rest:
overrides, files, streaming, steering, cancelling, the trace and the archive.

## 6. Add members

The owner's key does everything in the org. Give each person their own key:

```bash
curl -s -X POST $HI/v1/members -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"name": "dev"}'
curl -s -X POST $HI/v1/members/dev/keys -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"label": "laptop"}'
```

A member reads the org's providers, sandboxes and harnesses, makes requests, and sees only their own
sessions. Their harness `$HOME` is theirs, seeded from the folder on first use.
