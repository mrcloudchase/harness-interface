<p align="center">
  <img src="docs/media/picky.png" width="280" alt="Picky, the harness-interface mascot: a hermit crab with no shell of its own">
</p>

<h1 align="center">harness-interface</h1>

<p align="center">
  <b>One API in front of every harness. Send a request, it runs in a sandbox, the output comes back.</b><br>
  Providers, sandboxes and harnesses are resources you add over the API. The server has no code for any of them.
</p>

<p align="center">One command, four harnesses: each writes a haiku, then titles it in the same conversation with <code>-c</code>.</p>

<table align="center">
  <tr>
    <td align="center"><b>Claude Code</b><br><img src="docs/media/run-claude-code.gif" width="420" alt="hi run claude-code: a haiku, then its title in the same conversation"></td>
    <td align="center"><b>Codex</b><br><img src="docs/media/run-codex.gif" width="420" alt="hi run codex: a haiku, then its title in the same conversation"></td>
  </tr>
  <tr>
    <td align="center"><b>Hermes</b><br><img src="docs/media/run-hermes.gif" width="420" alt="hi run hermes: a haiku, then its title in the same conversation"></td>
    <td align="center"><b>Pi</b><br><img src="docs/media/run-pi.gif" width="420" alt="hi run pi: a haiku, then its title in the same conversation"></td>
  </tr>
</table>

---

A harness is any program you can start from a shell and hand a task to: Claude Code, Codex,
OpenCode, Aider, the one you wrote yourself. Each has its own flags, its own output
format, its own way of taking a key and of resuming a session. harness-interface puts one API in
front of all of them.

You add a provider, pick a sandbox and add a harness. You send a request in the OpenAI Responses
wire format, with the harness's name as the `model`. The server runs the harness inside the
sandbox, streams the harness's own output back unchanged, and keeps a record of the run. Send
`previous_response_id` and the same harness picks the conversation up where it left off.

```
PUT  /providers/anthropic    a url and a key
PUT  /sandboxes/python-dev   a Dockerfile; a locked-down `default` is built in
PUT  /harnesses/claude-code  how one CLI is run; which provider, which sandbox
POST /responses              {"model": "claude-code", "input": "Fix the failing test."}
POST /responses              {"model": "claude-code", "input": "Now add a test for it.", "previous_response_id": "resp_…"}
```

## Why

**One request shape for every harness.** The request is the Responses shape clients already
speak. `model` names the harness, or `harness/model` to pick its model too.
`previous_response_id` continues the conversation. What streams back is the harness's own output,
line for line, so nothing is lost in translation.

**Any provider on any harness, with no server code.** A provider is a url and a key. Each
harness's run script decides which of the CLI's variables get them. Pointing Claude Code at
DeepSeek means changing one word in its `harness.json`. The server never learns what that word means.

**Every run in a sandbox.** Each response runs in a fresh container. All capabilities are
dropped and the root filesystem is read-only. Its private network has exactly one way out: a
tunnel to the harness's provider. The harness can call its model and nothing else, and it cannot
use the tunnel for anything else either.

**Runs belong to the server.** Many clients run harnesses at once, each request in its own
sandbox. A client can disconnect and the run still finishes and is recorded. Any run can be
cancelled, even while its sandbox is still being built.

**Adding anything is a PUT.** A provider is three fields. A sandbox is a Dockerfile. A harness is
a folder of small files. Change any of them and the next request uses the change, with no restart.

**Twenty-three harnesses ship ready.** [harnesses/](harnesses/) holds 23 harnesses, each a folder,
registered with one loop. The built-in sandbox already has every one of their CLIs. Every one is
tested on a first turn and on a resumed second turn.

**Small enough to read.** The whole server is fourteen Python modules and about 1,200 lines.

## Try it

You need git, and Docker for sandboxed runs. The installer brings the rest: uv, Python, the
server and `hi`, its command line.

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh

hi server start
hi provider add anthropic --url https://api.anthropic.com --key-env ANTHROPIC_API_KEY
hi harness add --builtin claude-code
hi run claude-code "What is 17 * 23?"
hi run claude-code "And what is that times 2?" -c
```

`hi` is one way in; the API is the product. The [CLI guide](docs/cli.md) covers every command,
and the [walkthrough](docs/walkthrough.md) makes the same calls with `curl`.

## How it fits together

```
           you add, over the API, at any time
  ┌──────────────┬────────────────────────┬───────────────────────────────┐
  │ providers    │ sandboxes              │ harnesses                     │
  │ url + key    │ Dockerfile + egress    │ scripts + run config          │
  │              │ (`default` built in)   │ + a provider + a sandbox      │
  └──────┬───────┴───────────┬────────────┴───────────────┬───────────────┘
         ▼                   ▼                            ▼
POST /responses ─► harness-interface ─► its own network ─► the harness's output, streamed,
{model, input,     builds the image     one container      then the record: status, answer,
 previous_         once, opens the      for the harness,   usage, cost, files, the session
 response_id}      egress door          one door out       to resume
```

The server promises every harness the same things inside its sandbox: the task, the model, the
provider's url and key, the session to resume, and a file to write back what happened. The
contract, the resource shapes, every endpoint and exactly what the sandbox enforces are in
[docs/reference.md](docs/reference.md).

## Verified

All 23 shipped harnesses were added through the API to a running server and run in the default
sandbox image on Docker. Each one answered a first request, and each one continued the
conversation on a second request with `previous_response_id`. Inside a live run, the sandbox
reached its provider and nothing else. The details are in [docs/reference.md](docs/reference.md#verified).

## Meet Picky

Picky is a hermit crab with no shell of its own. A hermit crab doesn't grow a shell; it finds
one that fits, wears it, and moves to another when it needs to. Picky does that with harnesses.
Claude Code for one request, Codex for the next, the one you wrote yourself after that: each
harness is a shell Picky puts on to get the work done, and takes off again. Picky stays the same
underneath, the way every request goes through the same API whichever harness serves it.

## Docs

- [CLI](docs/cli.md): install, start the server, and every `hi` command.
- [Walkthrough](docs/walkthrough.md): the API by hand: add a provider, register a harness, first request, continue.
- [Reference](docs/reference.md): resources, the process contract, the wire format, endpoints, a request end to end, the sandbox, configuration, layout.
- [Harnesses](harnesses/README.md): the 23 that ship, registering them, and what each one needs.

## Status

Single tenant, localhost, no authentication. This is the base layer: one interface to any
harness, and a record of everything each one did. Comparing harnesses on the same task, judging
their output and routing between them are the layers that come next. All of them build on this
record without changing it.
