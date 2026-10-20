# The harness survey

Before the 2.0.0 rebuild, 23 coding CLIs were installed and driven directly, with no harness-interface
in between, to learn what a harness folder has to do for each: how it takes a task, which provider
settings it reads, which config artifacts it loads and from where, what it prints, where it keeps its
state, how a conversation resumes, how (and whether) it takes more text while it works, and what it
does when stopped. Each was tested live: a resume (remember a word, recall it), a steer while it
counts with sleeps, and a stop then continue.

- [SUMMARY.md](SUMMARY.md) has the verdicts, the steering patterns (stream-json on stdin, the CLI's own
  RPC, ACP, a local HTTP server, a local WebSocket gateway, a REPL and SIGINT, an in-process SDK, a
  hook bridge), what each implies for a folder, and what the sandbox has to allow or quiet.
- `<name>.md` is one CLI's survey: inputs, provider, artifacts it loads, outputs, state, continue,
  mid-turn steering, graceful stop, worst case, and the folder to ship.

The surveys describe the 1.x folders and contract as they were: "today's folder", `report.py`,
`HI_SESSION_ID` and a key in the environment are 1.x. Contract 1 took up what they asked for: line 1
plus steer lines on stdin, SIGINT for a graceful stop, an early, atomic `HI_OUTPUT` with
`status: running | ok | fail | stopped`, `resume`, `steers` and fixed `usage` keys, `HI_PROVIDER_API`,
`files` and `home/` under `$HOME`, `NO_PROXY` for loopback, and the key in a gateway or a read-only
file, never the environment. Write a new folder to the [contract](../../users/harness-contract.md),
and read a survey for how its CLI behaves.

Five are built as folders in [`harnesses/`](../../../harnesses/README.md). The other 18 are the next
ones to build; start a folder from its survey, and note that versions and flags move: check the
current release before relying on any detail here. Versions are those of October 2026.
