# Harnesses

Each folder here is a harness: everything about one coding CLI, from how it installs to what it
reports back. The server has no code for any of them. [Harness folders](../docs/users/harnesses.md)
explains the parts and how to write one; the [harness contract](../docs/users/harness-contract.md) is
the reference.

| Folder | CLI | Default provider | Shapes it speaks | Driven through |
|---|---|---|---|---|
| [claude-code](claude-code/) | Claude Code 2.1.305 | `https://api.anthropic.com` | anthropic-messages | stream-json on stdin; a steer is a user line, a stop an `interrupt` control request |
| [codex](codex/) | Codex CLI 0.163.0 | `https://api.openai.com/v1` | openai-responses | `codex app-server` JSON-RPC: `turn/steer`, `turn/interrupt` |
| [pi](pi/) | pi 1.3.0 | `https://api.anthropic.com` | anthropic-messages, openai-chat, openai-responses | `pi --mode rpc`: a steering prompt, `abort` |
| [opencode](opencode/) | OpenCode 1.19.3 | `https://api.anthropic.com` | anthropic-messages, openai-responses, openai-chat | `opencode serve` on loopback and its event stream: `prompt_async`, `abort` |
| [hermes](hermes/) | Hermes Agent 0.19.0 | `https://api.anthropic.com` | anthropic-messages, openai-chat | ACP over stdio: a `/steer` prompt, `session/cancel` |
| [template](template/) | a stand-in CLI | — | all three | a starting point: copy it, and replace its parts |

All five are `steered`: text sent while they work reaches the running work, a stop is graceful, and a
stopped session continues where it left off. Each has been proven with the live suite, sandboxed,
from the library and the API, under the gateway and with a key file.

Each folder's `home/` holds one harmless example of each config artifact the CLI loads (a skill, an
MCP server, a hook), named `hi-live-…` so the live suite can check it is loaded. Replace them with
yours.

## Register one

The server takes a folder as a JSON map of relative path to content. From a checkout:

```python
import base64, json, pathlib, urllib.request

def put_harness(folder, server="http://127.0.0.1:8000"):
    root = pathlib.Path(folder)
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            data = p.read_bytes()
            try:
                files[p.relative_to(root).as_posix()] = data.decode()
            except UnicodeDecodeError:
                files[p.relative_to(root).as_posix()] = {"base64": base64.b64encode(data).decode()}
    req = urllib.request.Request(f"{server}/harnesses/{root.name}", method="PUT", data=json.dumps(files).encode(),
                                 headers={"content-type": "application/json"})
    return json.load(urllib.request.urlopen(req))

print(put_harness("harnesses/claude-code"))
```

Its install starts at once, in the background; `GET /harnesses/claude-code` shows `installing`,
`ready` or `failed`, with the log.

## More harnesses

Eighteen more CLIs were surveyed before these were built: Aider, CheetahClaws, Cline, DeepSeek Harness,
Gajae Code, Goose, Grok CLI, harness-engineering, J-Code, Kilo Code, Kimi Code, MiMo Code, MiniMax Code,
nanobot, OMP, OpenHands, OpenSquilla and Qwen Code. All of them can be driven this way. How each takes a
task, loads its config, resumes, steers and stops is in
[the harness survey](../docs/contributors/harness-survey/README.md); that is where a folder for one of
them starts.
