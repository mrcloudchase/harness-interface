# Security

What a sandbox can reach, where keys live, and what you must protect.

## Keys

- A provider's key is sealed with AES-256-GCM under the master key the moment it arrives, bound to
  its record, and the API never returns it.
- It is opened at one moment: when a run's egress door is started, in that process's memory, for
  that run. The door dies with the run.
- A run holds a session token, not the key, in `HI_PROVIDER_KEY_FILE` and the variable
  `harness.json` names. The gateway accepts that token from that run's network and nothing else;
  elsewhere it is worthless.
- The server's own API keys are kept as digests. The master key is in `HI_MASTER_KEY` or a file
  with mode 600; lose it and the providers must be re-entered.

So: a compromised container yields a token that dies with it, a compromised door yields one key for
one run, and a copy of the data directory without the master key yields ciphertext.

## The sandbox

Every turn: a fresh container from the org's image, no capabilities, no privilege escalation, a
read-only root, an unprivileged user, memory and process limits, `/tmp` in memory. It sees the
harness folder and its tools (read-only), the member's home and the session's workspace and run
directory (read-write), and nothing else of the host or of any other org, member or session.

Its network is internal. The door is the only way out: it tunnels TLS to the sandbox's `egress`
hosts and the install's, refuses every other host, and resolves no names for the run. The provider
is reached only through the gateway.

## Tenancy

Every record and path is under its org. A key resolves to one member of one org; every route
checks the org of what it touches and answers 404 for anything else. Members see their own sessions;
owners see the org's.

## What you protect

- The server speaks plain HTTP. Put TLS in front, and a network boundary.
- `HI_ADMIN_KEY` creates orgs and nothing else. Keep it with your sign-up service.
- `HI_DATA_DIR` holds everything. Back it up with the master key, separately.
- A harness's `request.sh` runs what the org wrote, with the org's provider, in the org's sandbox.
  The org is responsible for what it uploads, as it would be for a script on its own machines.
- Secrets a harness needs beyond the provider (a deploy key, a registry token) belong in the org's
  `seeds/` or a request file: the org chooses, and the trace never holds `$HOME`.
