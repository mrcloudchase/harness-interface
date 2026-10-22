# Getting started

Ten minutes on one box: the platform, a tenant, a provider, a package, a request.

You need Docker running. Workers bind-mount session trees into sandboxes by their host paths, so the
data directory must be the same path inside and outside the platform's container; the compose file
below mounts `/srv/hi/data` on both sides.

## 1. Start it

```bash
mkdir -p /srv/hi/data && cd deploy
docker compose --profile one-box up -d
docker compose exec platform harness-interface init --tenant acme --owner chase
```

`init` writes the master key into the data directory, sets the **deployer key** (shown once; it
manages tenants and the fleet), and creates the tenant `acme` with `chase` as its owner, printing
the **owner's API key** once. Keep both. Open `https://localhost` for the console, or use the API
directly as below.

Without Docker Compose, the same thing from a checkout:

```bash
uv tool install "git+https://github.com/mrcloudchase/harness-interface@v4.0.0"
harness-interface init --tenant acme --owner chase
harness-interface serve            # every role in one process; the API on 127.0.0.1:8000
```

## 2. Add a provider

A provider is a model endpoint and its key. The key is sealed on arrival; `GET` never returns it.

```bash
export HI="http://127.0.0.1:8000" KEY="hi_…"
curl -s -X PUT $HI/v1/providers/deepseek -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"url": "https://api.deepseek.com/anthropic", "api": "anthropic-messages", "key": "sk-…"}'
```

`api` is the shape the endpoint speaks: `anthropic-messages`, `openai-chat`, `openai-responses`, or
`none` for an endpoint of your own that adds its credential itself.

## 3. Fork a package from the catalog

```bash
curl -s $HI/v1/catalog -H "Authorization: Bearer $KEY" | python3 -m json.tool | grep '"name"'
curl -s -X PUT $HI/v1/harnesses/claude-code -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"catalog": "claude-code"}'
```

The fork is yours: a package with `harness.json`, `install.sh`, `request.sh` and seeds, stored by the
digest of its files. Its `defaults` name a provider (`deepseek` for this one) and a model; register
the provider under that name, or name your own in the request's model path below. To change the
package, download the catalog folder from the repository, edit it, `tar czf` it and `PUT` the
archive to the same name. See [the catalog pages](harnesses/) for each package's folder and notes.

## 4. Make a request

Any OpenAI Responses client works. `model` is the harness name, which takes the package's defaults,
or `harness/provider/model` to choose the provider and model for this turn.

```bash
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Create hello.py that prints hello, run it, and say done."}'
```

```python
from openai import OpenAI
client = OpenAI(api_key="hi_…", base_url="http://127.0.0.1:8000/v1")
r = client.responses.create(model="claude-code/deepseek/deepseek-chat", input="Create hello.py that prints hello, run it, and say done.")
print(r.status, r.output_text)
```

The first request for a package runs its `install.sh` once in the sandbox base image (a minute or
two for a Node CLI) and caches the result on the worker. The reply's one output message is what the
package's `response.sh` returned, or `request.sh`'s stdout when the package has no `response.sh`;
`status` is `completed` when the package exited 0. `metadata.session_id` names the session.

## 5. Continue, stream, steer

```python
r2 = client.responses.create(model="claude-code", input="Now add a test.", previous_response_id=r.id)
for event in client.responses.create(model="claude-code", input="Explain the test.", previous_response_id=r2.id, stream=True):
    if event.type == "response.output_text.delta":
        print(event.delta, end="")
```

A continuation runs in the same workspace with the same member home, so the CLI resumes. Streaming
delivers `request.sh`'s stdout as it happens. While a turn runs, `POST /v1/sessions/{id}/interrupt`
with `{"input": "…"}` steers it and `POST /v1/responses/{id}/cancel` stops it. `GET /v1/sessions/{id}/archive`
is the workspace as a tarball; `/trace` is everything that happened. [Requests](requests.md) has all of it.

## 6. Add people

```bash
curl -s -X POST $HI/v1/members -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"name": "dev"}'
curl -s -X POST $HI/v1/members/dev/keys -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"label": "laptop"}'
```

Members request and see their own sessions; owners register things and see everyone's. The console
at `/` does all of the above from a browser.
