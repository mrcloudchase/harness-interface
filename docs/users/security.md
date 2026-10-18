# Security

What harness-interface protects, how, and what it leaves to you.

## The model

A coding harness runs a model that writes and runs commands. harness-interface assumes those
commands could do anything. With the Docker runtime, it keeps them inside a container that:
- **can reach its model provider and nothing else**, besides any hosts its sandbox allows, so a
  harness can't exfiltrate data, reach your network, or download arbitrary code at run time;
- **can't escalate** out of an unprivileged user with no capabilities;
- **can't change its own image**, because the root filesystem is read-only;
- **is thrown away after the run.** Only the conversation's workspace persists.

## The sandbox

Every Docker run gets this hardening, whatever its sandbox's Dockerfile:

| Control | Setting |
|---|---|
| Privileges | every Linux capability dropped; `no-new-privileges` |
| User | never root: uid 1000 when the server runs as root, otherwise the server's own user |
| Filesystem | read-only root; writable only: the workspace, and a 512 MB `/tmp` |
| Limits | 512 processes, 4 GB of memory, and the harness's timeout |
| Network | an internal Docker network of its own, with no route to the internet, the host or other runs |
| Mounts | the conversation's workspace, read-write; the harness's scripts, read-only |

`/tmp` allows executables, as a normal `/tmp` does, because many CLIs unpack and load native
modules there.

## The egress door

A run's network has one other member: its egress door (`egress.py`). It is the only way out:
- **CONNECT only.** It opens a tunnel to a host and port on its allowlist, and nothing else.
- **The allowlist** is the provider's host and port, plus any hosts the sandbox names in
  `egress`. Nothing more.
- **Refuses everything else with a 403:** other hosts, other ports, plain HTTP, and requests
  aimed at the door itself.
- **No DNS in the sandbox.** The door resolves names itself, so the sandbox needs none.
- **Sees nothing it carries.** TLS stays end to end between the harness and the provider.
- **Locked down too:** it runs with every capability dropped and a read-only root.
- **Ready before the run.** The run starts only once the door is listening, so a harness that
  calls its provider at once is never left without a way out.

## Keys

- **At rest:** stored in `providers/` as files only their owner can read (mode 600), in a
  directory only its owner can enter (mode 700).
- **In the API:** never returned. Listing and reading providers shows names and urls only.
- **In a run:** passed to the container as environment variables, by name. The value travels in
  the Docker client's environment, so the server never puts it on a command line or in `ps`.
  Inside the sandbox, the harness's script hands it to its CLI as that CLI takes it; a few pass it
  as an argument, or let the CLI save it in its own state.
- **In `hi`:** read from an environment variable, a prompt or stdin, never from an argument.
- **In a CLI's own state:** CLIs keep sessions and credentials in the workspace's `.home/`. The
  server ignores it in `.git/info/exclude`, where no request can change that, so it is never
  committed, diffed, listed or served, not even while a run is going.

## What is not protected

- **The workspace is the harness's to change.** A harness can edit or delete anything in its
  conversation's workspace. Don't put anything there you aren't willing to have changed.
- **The provider is reachable.** A harness can spend your provider credit, and send anything it
  can read to the provider.
- **A harness can read its own provider key.** The key is in its environment so its CLI can call
  the provider, so a prompt can make the harness print it, write it to a file or send it on.
  Anything that can run a harness can get its key: use keys with spending limits.
- **The local runtime has no sandbox.** With `HI_RUNTIME=local`, a harness runs as you, with your
  files and your network. Use it for harnesses you trust, such as one you are developing.
- **The API has no authentication.** It binds to `127.0.0.1` by default. Anyone who can reach it
  can run harnesses with your keys, so don't expose it.
- **Harnesses are code you choose to run.** A harness's scripts run inside the sandbox with its
  CLI. Read a harness before you add it, as you would any script.

## Reporting

Report a security problem privately, through **Report a vulnerability** on the repository's
[Security tab](https://github.com/mrcloudchase/harness-interface/security), not in a public issue.
Say what you ran and what it exposed, and leave out any real key.
