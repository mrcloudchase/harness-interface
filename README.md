<p align="center">
  <img src="docs/media/picky.png" width="240" alt="Picky, the harness-interface mascot: a hermit crab with no shell of its own">
</p>

<h1 align="center">harness-interface</h1>

<p align="center">
  <b>A multi-tenant harness server. Bring your providers, your sandboxes and your harness folders; drive them through the OpenAI Responses API.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/runs-sandboxed%20in%20Docker-2496ed" alt="Runs sandboxed in Docker">
  <img src="https://img.shields.io/badge/API-OpenAI%20Responses-412991" alt="OpenAI Responses API">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0"></a>
  <a href="https://github.com/mrcloudchase/harness-interface/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mrcloudchase/harness-interface/ci.yml?branch=main&label=CI" alt="CI"></a>
</p>

<p align="center">
  <a href="docs/users/getting-started.md">Getting started</a> ·
  <a href="docs/users/harness-template.md">Harness template</a> ·
  <a href="docs/users/requests.md">Requests</a> ·
  <a href="docs/users/multi-tenant.md">Multi-tenant</a> ·
  <a href="docs/users/README.md">Docs</a>
</p>

---

**Meet Picky**, a hermit crab with no shell of its own. Hermit crabs don't grow shells; they find one
that fits, wear it, and swap it when they need to. Picky does that with coding harnesses: whichever
CLI your org brings, configured however your org likes, run in a sandbox your org chose.

harness-interface is the server behind that:

- **Orgs bring everything.** A provider is an endpoint and a key. A sandbox is an image or a
  Dockerfile. A harness is a folder: `harness.json`, `install.sh`, `request.sh` and seed files in the
  CLI's own formats. The server ships none of them and reads none of the CLI's configuration.
- **One request shape.** `POST /v1/responses`, as any OpenAI Responses client sends it. `model` is
  `sandbox/harness/provider/model`, or just the harness for its defaults; `previous_response_id`
  continues the session; `store: false` keeps nothing. The output is what the script printed,
  stdout and stderr, streamed or whole. Steer a running turn, cancel it, read the trace, download the
  workspace.
- **Nothing in the sandbox but the work.** A fresh locked-down container per turn, the member's own
  `$HOME` and the session's workspace mounted, an internal network with one door, and a session
  token where the key would be. The key is sealed at rest and opened only for that run's gateway.
- **Multi-tenant by construction.** Every record and path lives under an org; a key is a member's;
  owners register, members request, nobody sees another org. A hosted platform and a self-hosted box
  run the same code.

## Quickstart

```bash
uv tool install "git+https://github.com/mrcloudchase/harness-interface@v3.0.0"
harness-interface init --org acme --owner chase     # prints the owner's API key once
harness-interface serve
```

Register a provider, a sandbox and a harness folder, then ask:

```bash
curl -s localhost:8000/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "node22/claude-code/anthropic/deepseek-chat", "input": "Create hello.py that prints hello, run it, and say done."}'
```

[Getting started](docs/users/getting-started.md) walks through all of it in ten minutes, and
[the harness template](docs/users/harness-template.md) has a working Claude Code folder to copy.

## The folder

```
claude-code/
  harness.json      defaults (sandbox, provider, model), the variable names the CLI reads its credential from, the steer signal, caps
  install.sh        npm install @anthropic-ai/claude-code@… into $HI_TOOLS
  request.sh        claude -p "$(cat)" --output-format stream-json …; --continue on turn 2
  seeds/org/        .claude/CLAUDE.md and settings every member gets, every turn
  seeds/user/       what a member's $HOME starts with, then theirs
  seeds/project/    what a new workspace starts with; the repository wins
```

Two folders with different seeds are two harnesses: `claude-code-app1`, `claude-code-devteam`,
`codex-marketing`. A program of your own is a folder whose `request.sh` runs it.

## What comes back

```json
{"id": "resp_…", "status": "completed", "model": "node22/claude-code/deepseek/deepseek-chat",
 "output": [{"type": "message", "content": [{"type": "output_text", "text": "…stdout…"}]},
            {"type": "message", "content": [{"type": "output_text", "text": "…stderr…"}]}],
 "metadata": {"session_id": "sess_…", "harness": "claude-code", "version": "929aa748cf90e7cb", "turn": "1", "exit_code": "0"}}
```

Exit 0 is `completed`; anything else is `failed` with the code. Nothing is parsed or dropped. A loop,
an agent or a factory is a program you write against that shape;
[building on it](docs/users/building-on-it.md) shows four.

## Library

Python callers use the layers the server is built on, without HTTP:

```python
from harness_interface import Ask, Runtimes, Sessions, Store, Vault
store = Store(data_dir, Vault.from_env())
sessions = Sessions(store, Runtimes(data_dir / "logs", ca_file=None, owner=owner_of(data_dir)))
record = await sessions.wait((await sessions.create(Ask("acme", "chase", "claude-code", "Say hello."))).id)
print(record.status, record.stdout)
```

## Contributing

[AGENTS.md](AGENTS.md) says how the code is built and where a change goes;
[docs/contributors](docs/contributors/README.md) has the rest. Apache 2.0.
