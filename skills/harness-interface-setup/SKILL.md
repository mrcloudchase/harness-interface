---
name: harness-interface-setup
description: Set up a harness-interface server end to end and prove it works. Use when asked to install or configure harness-interface, register a provider, sandbox or harness folder, add members and keys, or make a first Responses API request against it. Covers both a self-hosted single-org server and an org on a hosted platform.
---

# Set up harness-interface end to end

harness-interface is a multi-tenant server that runs coding-agent CLIs ("harnesses") one turn at a
time in locked-down Docker containers and exposes them as the OpenAI Responses API. An org registers
three things: a **provider** (a model endpoint and its key), a **sandbox** (an image or Dockerfile),
and a **harness** (an uploaded folder with `harness.json`, `install.sh`, `request.sh`, `seeds/`).
Members then `POST /v1/responses` with `model` set to the harness name.

Work through the steps in order. Each step ends with a check; do not move on until it passes.
Never print, log or commit an API key, a provider key or the master key. Keys are shown once by the
server and never again; put them where the org keeps secrets and refer to them by environment
variable from then on.

## 0. Find out which path you are on

Gather: the server URL (`HI`), and the key you were given (`KEY`). Then classify the key:

```bash
export HI="https://hi.example.com" KEY="…"
curl -s -o /dev/null -w "%{http_code}\n" $HI/v1/me -H "Authorization: Bearer $KEY"
```

| Result | Meaning | Go to |
|---|---|---|
| connection refused | No server yet. You are the operator. | Step 1 |
| `403` | The platform admin key. It creates orgs and nothing else. | Step 2 |
| `200` with `"role": "owner"` | An org owner's key. | Step 3 |
| `200` with `"role": "member"` | A member's key. It can request but not register. Ask an owner for steps 3 to 5. | Step 6 |
| `401` | Unknown or revoked key. Stop and ask for a valid one. | |

## 1. Install and start the server (self-hosted operator only)

Needs Docker running and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install "git+https://github.com/mrcloudchase/harness-interface@v3.0.1"
harness-interface init --org <org> --owner <owner>      # prints the owner's API key ONCE
harness-interface serve                                  # 127.0.0.1:8000 by default
```

`init` writes `~/.harness-interface/data/master.key` (mode 600) and creates the org. `serve` reads
its settings from the environment: `HI_HOST`, `HI_PORT`, `HI_DATA_DIR`, `HI_MASTER_KEY` or
`HI_MASTER_KEY_FILE` (defaults to the file `init` wrote), `HI_ADMIN_KEY` (only for a hosted platform
that creates orgs over the API), `HI_CA_FILE` (a CA bundle when the network re-signs TLS). Put TLS in
front of it before anyone else reaches it. Run it under a process manager so it restarts; on start
it sweeps containers a crash left behind and marks their responses failed.

Check: `curl -s $HI/v1/me -H "Authorization: Bearer $KEY"` returns `{"org": …, "role": "owner"}`.
Continue at step 3 with that key.

## 2. Create the org (hosted platform admin only)

```bash
curl -s -X POST $HI/v1/orgs -H "Authorization: Bearer $ADMIN_KEY" -H 'content-type: application/json' \
  -d '{"name": "<org>", "owner": "<owner>", "max_runs": 4}'
```

The reply holds the owner's first key under `key.secret`. Hand it to the org's owner securely; it is
not shown again. `max_runs` is how many turns the org may run at once. Names (org, member, provider,
sandbox, harness) are lowercase letters, digits, dots, dashes and underscores, at most 63 characters,
starting with a letter or digit.

Check: `GET /v1/orgs` with the admin key lists it. Continue at step 3 with the owner's key.

## 3. Register a provider

A provider is a model endpoint, its API shape and its key. The key is sealed with AES-GCM on
arrival and `GET` never returns it.

```bash
curl -s -X PUT $HI/v1/providers/<name> -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d "{\"url\": \"<https base url>\", \"api\": \"<shape>\", \"key\": \"$PROVIDER_KEY\"}"
```

| `api` | Credential header the gateway adds | Typical `url` |
|---|---|---|
| `anthropic-messages` | `x-api-key` | `https://api.anthropic.com`, `https://api.deepseek.com/anthropic` |
| `openai-chat` | `Authorization: Bearer` | `https://api.openai.com/v1`, `https://api.deepseek.com/v1` |
| `openai-responses` | `Authorization: Bearer` | `https://api.openai.com/v1` |
| `none` | none; the endpoint adds its own | an internal proxy; `key` must be empty |

The URL must be `https://`. Register one provider per shape you need: a harness that speaks the
Anthropic shape and one that speaks OpenAI chat need two providers even for the same vendor.
The harness never sees this key: at run time it gets a per-session token and a gateway URL, and the
gateway swaps the token for the key.

Check: `GET /v1/providers/<name>` returns the name, url and api, and no key.

## 4. Register a sandbox

A sandbox is an image the org names or a Dockerfile it gives, plus the hosts a run may reach besides
its provider, and limits. Nothing of the platform or any harness is in it; the harness's CLI is
installed into a separate tools layer later.

```bash
# a plain image
curl -s -X PUT $HI/v1/sandboxes/node22 -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"image": "node:22-bookworm-slim", "egress": [], "memory": "4g", "pids": 512}'
# or a Dockerfile (built once; the build context is empty, so no COPY)
curl -s -X PUT $HI/v1/sandboxes/full -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"dockerfile": "FROM node:22-bookworm-slim\nRUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv git curl ca-certificates ripgrep procps && rm -rf /var/lib/apt/lists/*\n", "egress": []}'
```

Exactly one of `image` and `dockerfile`. `egress` is the list of hosts a *turn* may reach beyond its
provider; keep it empty unless the agent's work needs a package registry or git host. `install.sh`
has its own egress list in `harness.json`. Pick the base by what the CLI needs: Node CLIs run on
`node:22-bookworm-slim`; Python CLIs that need 3.12 on `python:3.12-slim` plus git and curl; CLIs
shipped as binaries need curl and ca-certificates to download.

Check: `GET /v1/sandboxes/<name>` echoes it. A Dockerfile is built on the first request that uses
it; a build failure comes back as that response's `error`.

## 5. Upload a harness folder

Start from a verified folder rather than writing one: the repository documents 22 of them, each page
holding the whole folder and the sandbox and provider it was proven on, at
`docs/users/harnesses/add-<name>.md` (index and table in `docs/users/harness-template.md`), for
Claude Code, Codex, Hermes Agent, pi, OpenCode, Kilo CLI, Qwen Code, Cline, Oh My Pi, goose, Kimi
Code, MiniMax Code, aider, OpenHands, Grok Build, CheetahClaws, MiMo Code, jcode, OpenSquilla,
nanobot, zeroclaw and the DeepSeek Harness. Copy the page's files into a directory named after the
harness, then edit `defaults` in `harness.json` to the sandbox and provider names you registered and
a model id that provider serves.

The folder's contract:

```
<name>/
  harness.json      launch settings (below)
  install.sh        runs once per sandbox image as root; puts the CLI under $HI_TOOLS ($HI_TOOLS/bin is on PATH)
  request.sh        runs once per turn as an unprivileged user in the workspace; prompt on stdin; stdout+stderr = the response; exit 0 = completed
  seeds/org/        copied into $HOME every turn, overwriting (managed settings, e.g. an org CLAUDE.md)
  seeds/user/       copied into $HOME on a member's first use only
  seeds/project/    copied into the workspace when a session starts, never overwriting
```

```json
{
  "contract": 3,
  "description": "what it is",
  "defaults": {"sandbox": "node22", "provider": "<provider name>", "model": "<model id>"},
  "provider_env": {"key": "ANTHROPIC_API_KEY", "url": "ANTHROPIC_BASE_URL"},
  "interrupt": "SIGUSR1",
  "install": {"egress": ["registry.npmjs.org"], "timeout_s": 1200},
  "run": {"timeout_s": 1800, "stop_timeout_s": 20}
}
```

`provider_env` names the variables the CLI reads its credential and base URL from; the server sets
them to the session token and the gateway URL. `request.sh` also always gets `HI_WORKSPACE`, `HOME`,
`HI_DIR` (scratch; `$HI_DIR/interrupt` is a steer's text), `HI_SESSION`, `HI_RESPONSE`, `HI_TURN`
(1, 2, 3… so the script knows to resume), `HI_MODEL`, `HI_INSTRUCTIONS`, `HI_PROVIDER_URL`,
`HI_PROVIDER_KEY_FILE`, `HI_HARNESS_DIR`, `HI_TOOLS`. Unknown keys in `harness.json` are refused by
name. If you must write a `request.sh` yourself, keep the verified pages' skeleton: `set -m` so the
CLI runs in its own process group and the steer signal reaches the script, a `turn` function that
runs the CLI with the prompt as an argument and resumes on later turns, and a USR1 trap that runs the
steer text as the next turn.

Upload:

```bash
tar czf <name>.tgz -C <name> .
curl -s -X PUT $HI/v1/harnesses/<name> -H "Authorization: Bearer $KEY" --data-binary @<name>.tgz
```

A `400` names what is wrong (a missing file, a script that does not parse, an unknown key, a seeds
directory other than `org`, `user`, `project`). Two different CLIs or two configurations of one CLI
are two folders under two names.

Check: `GET /v1/harnesses/<name>` shows `version` (the folder's digest) and your `defaults`.

## 6. Make the first request

Any OpenAI Responses client works. `model` is the harness name, which takes the folder's defaults,
or `sandbox/harness/provider/model` to choose all four (the model last, so it may contain slashes).

```bash
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "<name>", "input": "Create hello.txt containing the word hello, then reply with the one word: done"}'
```

The first request for a harness in a sandbox runs `install.sh` (minutes, once; cached per harness
version and image). The reply is a response object: `status` is `completed` when `request.sh` exited
0, `failed` otherwise with `error`; `output[0]` is stdout, `output[1]` is stderr; `metadata.session_id`
is the session. Nothing of the harness's output is parsed or reshaped, so read it as that CLI's own
format.

Check: `status` is `completed` and stdout shows the CLI's reply. Then prove the session continues:

```bash
curl -s $HI/v1/responses -H "Authorization: Bearer $KEY" -H 'content-type: application/json' \
  -d '{"model": "<name>", "input": "What file did you create? Reply with just its name.", "previous_response_id": "<id from above>"}'
curl -s $HI/v1/sessions/<session_id>/archive -H "Authorization: Bearer $KEY" -o ws.tgz && tar tzf ws.tgz | grep hello.txt
```

If you have the repository, `python scripts/live.py --url $HI --key $KEY --harness <name>` runs the
full nine-check suite (make, recall, archive, stream, interrupt accepted, steer, cancel, trace,
stateless) and prints PASS or FAIL per check.

## 7. Add members and keys

```bash
curl -s -X POST $HI/v1/members -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"name": "<member>", "role": "member"}'
curl -s -X POST $HI/v1/members/<member>/keys -H "Authorization: Bearer $KEY" -H 'content-type: application/json' -d '{"label": "laptop"}'
```

The key's `secret` is shown once. Members request, read their own sessions and mint or revoke their
own keys; owners do all of that for everyone and register providers, sandboxes and harnesses.
`DELETE /v1/keys/<id>` revokes. One org never sees another's anything.

## Using it after setup

- **Streaming**: `"stream": true` returns the standard Responses SSE events, deltas per stream.
- **Background**: `"background": true` returns at once with `in_progress`; poll `GET /v1/responses/<id>` or stream it later with `?stream=true`.
- **Files in**: `input` items of type `input_file` with `filename` and `file_data` (text or a `data:…;base64,` URL) land in the workspace before the turn.
- **Instructions**: `"instructions"` reaches `request.sh` as `HI_INSTRUCTIONS`; the folder decides what to do with it.
- **Steer**: `POST /v1/sessions/<sid>/interrupt` with `{"input": "…"}` while a turn runs; the verified folders deliver it as the next message once the current turn ends.
- **Cancel**: `POST /v1/responses/<id>/cancel`; the output so far is kept, status `cancelled`.
- **Stateless**: `"store": false` keeps the response and trace only; it cannot be continued.
- **Inspect**: `GET /v1/sessions/<sid>` (status, turns), `/trace` (every request, response, steer and cancel as sent), `/archive` (the workspace as a tarball). `DELETE /v1/sessions/<sid>` removes it.
- **Roll back a harness**: re-upload the previous folder; the same bytes are the same version. Sessions keep the version they started on.

## When something fails

| Symptom | Cause | Fix |
|---|---|---|
| `401` | No bearer, or an unknown or revoked key | Check the header; mint a new key |
| `403` | Wrong key kind for the route (admin vs owner vs member) | Use the key the table in step 0 says |
| `404 no provider/sandbox …` on a request | `defaults` name something not registered in this org | Register it, or fix `harness.json` and re-upload |
| `400 no sandbox: name one…` | The folder has empty defaults | Use the path form of `model` or fill `defaults` |
| `409 session … is running a response` | One turn at a time per session | Wait, cancel it, or start a new session |
| `error` starts with `install.sh exited` | The CLI did not install; the log tail follows | Fix `install.sh` or `install.egress` (the door refuses hosts not listed), re-upload |
| `error` starts with `image … failed to build` | The Dockerfile failed | Read the tail; fix the sandbox |
| `status: failed`, `request.sh exited N` | The CLI failed inside the turn | Read `output[1]` (stderr). A 401 from the model means the CLI sent something other than the session token; a refused host means it called somewhere not allowed |
| `status: incomplete` | Past `run.timeout_s` | Raise it in `harness.json` or shorten the task |
| `422` | Malformed body, e.g. `model` not a name or a four-part path | Fix the request |

Egress decisions are logged per session in the server's data directory under
`sessions/<org>/<member>/<harness>/<sid>/door.log` for the operator to read.
