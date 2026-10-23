# Clients

The request path is the OpenAI Responses API, so OpenAI's SDKs work unchanged. The session routes
are plain HTTP under the same base URL with the same key.

## The OpenAI SDK

=== "Python"

    ```python
    from openai import OpenAI

    client = OpenAI(api_key="hi_…", base_url="https://hi.example.com/v1")

    r = client.responses.create(model="claude-code", input="Create hello.txt containing hello, then say done.")
    print(r.status, r.output_text)
    session = r.metadata["session_id"]

    r2 = client.responses.create(model="claude-code", input="What did you create?", previous_response_id=r.id)
    print(r2.output_text)

    for event in client.responses.create(model="claude-code", input="Explain the repository.", stream=True):
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
    ```

=== "TypeScript"

    ```ts
    import OpenAI from "openai";

    const client = new OpenAI({ apiKey: "hi_…", baseURL: "https://hi.example.com/v1" });

    const r = await client.responses.create({ model: "claude-code", input: "Create hello.txt containing hello, then say done." });
    console.log(r.status, r.output_text);

    const stream = await client.responses.create({ model: "claude-code", input: "Explain the repository.", stream: true });
    for await (const event of stream) {
      if (event.type === "response.output_text.delta") process.stdout.write(event.delta);
    }
    ```

=== "curl"

    ```bash
    curl -s https://hi.example.com/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
      -d '{"model": "claude-code", "input": "Create hello.txt containing hello, then say done."}'
    ```

What the SDK covers: create with `model`, `input` (text, messages, files), `instructions`,
`metadata`, `store`, `background` and `stream`; continue with `previous_response_id`; `retrieve`;
`cancel`. `usage` comes back null, since token counts belong to the provider calls the package
made and live in the captures.

What it does not cover, because the Responses API has no shape for it: steering, the trace, the
captures, the archive, and administration. Those are plain routes:

```python
import httpx

hi = httpx.Client(base_url="https://hi.example.com", headers={"Authorization": "Bearer hi_…"})
hi.post(f"/v1/sessions/{session}/interrupt", json={"input": "Stop and summarize."})
trace = hi.get(f"/v1/sessions/{session}/trace").json()["data"]
captures = hi.get(f"/v1/responses/{r.id}/captures").json()["data"]
hi.get(f"/v1/sessions/{session}/archive").content
```

## Python in one process

The package can be driven without an API listener: the control plane, the worker and the
directory blob routes all run in your process over an in-memory transport, and only the gateway
needs a port, since the sandboxes reach it over the network. Docker is still required.

```python
import asyncio, httpx
from harness_interface.api.app import Service, create_app
from harness_interface.api.config import Settings
from harness_interface.gateway import Gateway, serve
from harness_interface.runtimes.docker import owner_of
from harness_interface.sandboxes import Node
from harness_interface.sessions import Ask
from harness_interface.worker import Worker

async def main():
    settings = Settings.from_env()
    service = Service(settings)
    transport = httpx.ASGITransport(app=create_app(service))
    node = Node(settings.base_image, owner_of(settings.data_dir), settings.runtime, settings.ca_file)
    worker = Worker(settings.public_url, node, settings.data_dir / "worker", name="here", slots=2,
                    version="4.0.0", join_token=service.join_token, transport=transport)
    gateway = asyncio.create_task(serve(Gateway(service.store, service.blobs), "0.0.0.0", settings.gateway_port))
    runner = asyncio.create_task(worker.run())
    r = service.sessions.create(Ask("acme", "chase", "claude-code", "Create hello.txt containing hello, then say done."))
    r = await service.sessions.wait(r.id)
    print(r.status, r.output)
    runner.cancel(); gateway.cancel()

asyncio.run(main())
```

The `Ask` names the tenant and member directly, so no API key is involved; the tenant, provider
and package must already exist in the store.

## The live suite and the demo

Two scripts in the repository drive a running platform the way a client would:

```bash
python scripts/live.py --url https://hi.example.com --key $KEY --harness claude-code   # the nine checks
python scripts/demo.py --url https://hi.example.com --key $KEY --harness claude-code   # a streamed turn and a steer, in the terminal
```

Next: [Tenants and limits](tenants.md).
