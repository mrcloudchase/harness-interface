# AGENTS.md

Read this before changing anything here. It says what harness-interface is for, the principles every
change keeps, how a turn flows through the code, and where each kind of change goes. The detail is in
[docs/contributors](docs/contributors/README.md) and [docs/users](docs/users/README.md).

## What this is

harness-interface is a multi-tenant harness server. An org registers providers (endpoint plus key),
sandboxes (image or Dockerfile, egress, limits) and harnesses (an uploaded folder: `harness.json`,
`install.sh`, `request.sh`, `seeds/`). A member sends an OpenAI Responses request naming a harness;
the server runs `request.sh` once, in a fresh container of the sandbox, with the member's `$HOME`
and the session's workspace mounted and a session token standing in for the provider's key, and
returns everything the script printed as the response. It steers, cancels, traces and archives.
It knows nothing about any CLI. [VISION.md](VISION.md) is the owner's direction.

## Founding principles

1. **The server runs the script and relays the bytes.** It reads three files from a folder and
   copies the rest; it parses nothing a harness prints. No branch on a harness's name, no CLI flag,
   no output format, anywhere in the server.
2. **Configuration is the org's artifact.** Providers, sandboxes and harness folders are resources
   an owner puts; the next request uses them. Org, member and project settings are seed files in the
   CLI's own formats, copied by rule: `seeds/org` every turn, `seeds/user` once, `seeds/project` at a
   session's start.
3. **One request shape.** `model` is the harness, `metadata` overrides sandbox, provider and model,
   `previous_response_id` continues, `store` decides what stays. The output is stdout and stderr as
   two messages, the exit code as the status. Any Responses client works unchanged.
4. **A tenant is a prefix.** Every record and path lives under its org; a key is a member's; every
   route checks the org of what it touches and answers 404 otherwise. Hosted and self-hosted are
   the same code.
5. **Nothing of value in the sandbox.** A fresh locked-down container per turn, an internal network
   with one door, a session token where the key would be. The key is sealed at rest and opened only
   to start that run's door.

## How it is built

Seven layers, each importing only downward ([architecture](docs/contributors/architecture.md)):
execution and the vault (0); process, Docker, door (1); the folder (2); the store (3); sandboxes and
tools layers (4); sessions and turns (5); the wire format and the routes (6).

## Where a change goes

- A new field in a request or response: `api/wire.py`.
- A new route or permission: `api/app.py`.
- What a turn is given, how a steer or cancel lands, what is kept: `sessions.py`.
- What `harness.json` may say: `harness.py`, and the template page in the user docs.
- What an org can register: `store.py`.
- How a container is run or locked down: `runtimes/docker.py` and `runtimes/door.py`.

Every change has a test beside it; the fakes in `tests/fakes.py` stand in for Docker. Never commit a
key, a model identifier or a harness folder: the repository ships none.
