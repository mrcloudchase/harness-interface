# Getting started

By the end of this tutorial you will have:
- installed harness-interface;
- run Claude Code in a sandbox;
- continued the conversation;
- read everything the run produced;
- run a second harness through the same commands.

It takes about ten minutes, most of it the one-time sandbox build.

**You need:** Linux or macOS, git, Docker (running), and an Anthropic API key.

## 1. Install

```bash
curl -fsSL https://raw.githubusercontent.com/mrcloudchase/harness-interface/main/install.sh | sh
```

This installs the latest release: `harness-interface`, the server, and `hi`, its command line. If
`hi` isn't found afterwards, open a new terminal.

## 2. Start the server

```bash
hi server start
```

```
server running at http://127.0.0.1:8000 (pid 4260); log: ~/.harness-interface/server.log
```

The server runs in the background, for you only: it listens on `127.0.0.1`, with no
authentication. It keeps everything it stores in `~/.harness-interface/data`.

## 3. Add a provider

A provider is where a harness's model calls go, and the key that unlocks them:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
hi provider add anthropic --url https://api.anthropic.com --key-env ANTHROPIC_API_KEY
```

`--key-env` reads the key from the environment, so it never appears in your shell history.

## 4. Add a harness

Twenty-three harnesses ship with harness-interface. Add Claude Code:

```bash
hi harness add --builtin claude-code
```

```
harness claude-code (provider anthropic, sandbox default)
```

It uses the `anthropic` provider you just added. It runs in `default`, the built-in sandbox, which
has every shipped harness's CLI installed.

## 5. Run it

```bash
hi run claude-code "Write a haiku about a hermit crab trying on shells."
```

The first run builds the sandbox image. That takes a few minutes, and nothing is shown until it is
done. After that, runs start in seconds.

While Claude Code works, its own output streams to your terminal. When it finishes, `hi` prints the
answer, then a summary line:

```
Tiny tenant seeks—
Each spiral doorway too tight,
One home clicks just right.
completed · 21.1s · $0.1174 · resp_254e3da1d07b4a5f
```

The summary shows the status, how long the run took, its cost, any files it produced, and the
response id. Claude Code ran in a fresh container that could reach `api.anthropic.com` and nothing
else.

## 6. Continue the conversation

```bash
hi run claude-code "Now give it a title." -c
```

`-c` continues the last response. The harness picks up its own session, so it remembers the haiku,
and its workspace still has any files from the first turn.

## 7. Look at what happened

```bash
hi ls                          # every response
hi show resp_254e3da1d07b4a5f  # the full record: status, usage, cost, files, session
hi output resp_254e…           # Claude Code's own output, exactly as it printed it
hi log resp_254e…              # its stderr
hi diff resp_254e…             # what it changed, as a diff
hi files resp_254e… PATH       # one of its files, as it left it
```

## 8. Run another harness the same way

Every harness takes the same commands. Add an OpenAI key and run Codex:

```bash
export OPENAI_API_KEY=sk-...
hi provider add openai --url https://api.openai.com/v1 --key-env OPENAI_API_KEY
hi harness add --builtin codex
hi run codex "Write a haiku about a hermit crab trying on shells."
```

## 9. Stop and cancel

- Press **Ctrl-C** during `hi run` to cancel the run. The container is killed and removed.
- `hi run … --detach` starts a run and returns its id; `hi cancel <id>` stops it later.
- `hi server stop` stops the server. Your providers, harnesses and records stay for next time.

## Next

- [Harnesses](harnesses.md): wrap your own CLI in two files.
- [Calling the API from code](api-clients.md): everything `hi` does is an HTTP call, and the OpenAI
  SDK works as a client.
- [The Python library](library.md): run a harness from Python, with no server.
