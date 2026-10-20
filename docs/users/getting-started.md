# Getting started

By the end you will have run Claude Code in a sandbox through the API, continued its session, steered
it while it worked, and read everything it did. It takes about ten minutes.

**You need:** Linux or macOS, git, Docker (running), and an Anthropic API key (or any provider that
serves the Anthropic Messages shape).

## 1. Install and start the server

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
harness-interface
```

The server runs in the foreground on `http://127.0.0.1:8000`, for you only: it has no authentication.
It keeps what it stores in `~/.harness-interface/data`. Leave it running and open another terminal.

## 2. Add a provider

A provider is where a harness's model calls go, and the key for them:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 -c 'import json, os; print(json.dumps({"url": "https://api.anthropic.com",
  "api": "anthropic-messages", "key": os.environ["ANTHROPIC_API_KEY"]}))' \
| curl -s -X PUT localhost:8000/providers/anthropic -H 'content-type: application/json' -d @-
```

```json
{"name": "anthropic", "url": "https://api.anthropic.com", "api": "anthropic-messages"}
```

The key is stored privately and never shown again. In a sandbox the harness never sees it either: it
gets a session token that the sandbox's gateway swaps for the key.

## 3. Add a harness

A harness is a folder. Get the shipped ones, and register Claude Code with the snippet from
[harnesses/README.md](../../harnesses/README.md#register-one):

```bash
git clone https://github.com/mrcloudchase/harness-interface && cd harness-interface
python3 - <<'EOF'
import base64, json, pathlib, urllib.request
root = pathlib.Path("harnesses/claude-code")
files = {}
for p in sorted(root.rglob("*")):
    if p.is_file():
        data = p.read_bytes()
        try:
            files[p.relative_to(root).as_posix()] = data.decode()
        except UnicodeDecodeError:
            files[p.relative_to(root).as_posix()] = {"base64": base64.b64encode(data).decode()}
req = urllib.request.Request("http://127.0.0.1:8000/harnesses/claude-code", method="PUT",
                             data=json.dumps(files).encode(), headers={"content-type": "application/json"})
print(json.load(urllib.request.urlopen(req))["install"])
EOF
```

Its install starts in the background: the first time, the server builds a small base image (about
400 MB, a minute or two) and installs Claude Code into a cached tools directory. Check on it:

```bash
curl -s localhost:8000/harnesses/claude-code | python3 -c 'import json,sys; print(json.load(sys.stdin)["install"]["state"])'
```

When it says `ready`, every session after starts in seconds.

## 4. Run it

```bash
curl -s localhost:8000/responses -H 'content-type: application/json' \
  -d '{"model": "claude-code", "input": "Write hello.py that prints hello, and run it.",
       "instructions": "Be brief."}' > first.json
python3 -c 'import json; r = json.load(open("first.json")); print(r["status"], r["output"][0]["content"][0]["text"])'
```

Claude Code ran in a fresh, locked-down container whose only way out was a gateway to `api.anthropic.com`,
holding a session token rather than your key.
The response has everything it did under `harness`: its own output (`stdout`), the files it changed
(`changes`, with their contents), a diff, the session id and its resume handle.

## 5. Continue the session

```bash
curl -s localhost:8000/responses -H 'content-type: application/json' \
  -d "{\"model\": \"claude-code\", \"input\": \"Now make it print goodbye too.\",
       \"previous_response_id\": \"$(python3 -c 'import json; print(json.load(open("first.json"))["id"])')\"}" \
| python3 -c 'import json,sys; r = json.load(sys.stdin); print(r["status"], r["harness"]["changes"])'
```

Same workspace, same `hello.py`, and Claude Code resumed its own conversation.

## 6. Steer it while it works

Start something long, streamed, and put more text into it while it runs:

```bash
curl -sN localhost:8000/responses -H 'content-type: application/json' -D headers.txt \
  -d '{"model": "claude-code", "stream": true,
       "input": "Write the numbers 1 to 30 to count.txt, one shell command per number, each followed by sleep 1. No loops."}' &
sleep 15
SESSION=$(grep -i x-session-id headers.txt | cut -d' ' -f2 | tr -d '\r')
curl -s localhost:8000/sessions/$SESSION/interrupt -H 'content-type: application/json' \
  -d '{"input": "Stop counting now. Write DONE to done.txt instead."}'
```

The reply's `outcome` is `steered`: the text went into the running work, and Claude Code stops counting
at its next step. `POST /sessions/$SESSION/stop` stops it instead, gracefully.

## Next

- [Harness folders](harnesses.md): configure a harness your way, or write one.
- [Calling the API from code](api-clients.md): the OpenAI SDK, streaming, agents and loops.
- [The Python library](library.md): the same, with no server.
