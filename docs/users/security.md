# Security

What harness-interface protects, how, and what it leaves to you.

## The model

A coding harness runs a model that writes and runs commands. harness-interface assumes those commands
could do anything. Under the Docker runtime (the default), every install and every response runs in a
fresh container that:
- **can reach its model provider and nothing else**, besides hosts its folder lists in `run.egress`, so
  it can't exfiltrate data to anywhere else, reach your network, or fetch code at run time;
- **never holds the provider's key**, by default: it gets a session token that only its own gateway
  accepts;
- **can't escalate** out of an unprivileged user with no capabilities, and **can't change its image**;
- **is thrown away when the response ends.** Only the session's workspace (with the CLI's `.home/`)
  persists, on the server.

## The sandbox

Every container, whatever its image:

| Control | Setting |
|---|---|
| Privileges | every Linux capability dropped; `no-new-privileges` |
| User | never root: uid 1000 when the server runs as root, otherwise the server's own user |
| Filesystem | read-only root; writable only: the session's workspace, the response's result file, and a 512 MB `/tmp` |
| Limits | 512 processes, 4 GB of memory, and the folder's `run.timeout_s` |
| Processes | tini as PID 1, so a stop reaches the harness's whole process group, and a kill follows |
| Network | an internal Docker network of its own, with no route to the internet, the host or other runs, and no DNS |
| Mounts | the workspace, read-write; the harness folder and its installed tools, read-only; the credential, read-only |
| Environment | exactly the [contract's variables](harness-contract.md#what-a-harness-is-given), passed by name; nothing of the server's |

`/tmp` allows executables, as a normal `/tmp` does, because many CLIs unpack native modules there.

An install runs in the same hardened container, with no provider and no credential at all, reaching only
the folder's `install.egress` hosts. A harness's tools directory is read-only to every response after.

## The egress door

A run's network has one other member: its door, the only way out. It runs locked down too (no
capabilities, a read-only root, an unprivileged user), and the run starts only once it is listening.

- **The CONNECT door** tunnels to the hosts on its allowlist, and refuses anything else with a 403:
  other hosts, other ports, plain HTTP. It resolves names itself and sees nothing it carries: TLS stays
  end to end.
- **The provider gateway** (`http://hi-provider:8080`, the same on every run) is a reverse proxy to the
  one provider the session uses. A request must present the session's token as its credential; the
  gateway swaps it for the real key in the header the API shape uses, and forwards over TLS.

The door logs one line per decision (the host, method and path; never a query, token or key) to
`logs/<response id>.door` in the data directory, so a refused host is plain to see.

## Keys

- **At rest:** each provider is a file only its owner can read (mode 600), in a directory only its
  owner can enter (mode 700).
- **In the API:** never returned. Reading providers shows the name, URL and shape.
- **In a response, under the gateway** (the default): the key goes to the door on its stdin, and never
  enters the harness's container. The harness reads a session token from `HI_PROVIDER_KEY_FILE`, which
  is worthless anywhere but at that run's gateway, and only while the run lasts.
- **In a response, in file mode** (`"credential": "file"`, for a CLI that must call the provider
  itself): the key is the file at `HI_PROVIDER_KEY_FILE`, mounted read-only, and the provider's host is
  on the door's allowlist. The harness can read it.
- **Never** on a command line, in an environment variable, a record, a log or a response. The live
  suite searches every log, record, workspace and the container's environment for the key after every
  check.
- **On this machine** (`HI_RUNTIME=local`): the same two modes, with the gateway on loopback. There is
  no sandbox, so nothing stops a harness from reading the server's files.

Secrets never go in a folder's `home/` or `workspace/`: they are copied into every session, and
anything in a session can be read by its harness.

## What is not protected

- **The workspace is the harness's to change.** It can edit or delete anything in its session's
  workspace, including `.home/`.
- **The provider is reachable.** A harness can spend your provider credit, and send anything it can
  read to the provider. Use keys with spending limits.
- **In file mode, a harness can read its key**, so a prompt can make it print it. Prefer the gateway.
- **The local runtime has no sandbox.** A harness runs as you, with your files and your network. Use it
  for harnesses you trust, such as one you are developing.
- **The API has no authentication.** It binds to `127.0.0.1` by default. Anyone who can reach it can
  run harnesses with your keys and read every session, so don't expose it.
- **A harness folder is code you choose to run.** Its `install.sh` and `run.sh` run in the sandbox with
  its CLI. Read a folder before you register it.

## Reporting

Report a security problem privately, through **Report a vulnerability** on the repository's
[Security tab](https://github.com/mrcloudchase/harness-interface/security), not in a public issue.
Say what you ran and what it exposed, and leave out any real key.
