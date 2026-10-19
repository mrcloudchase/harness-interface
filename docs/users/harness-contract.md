# Harness contract

What a harness is, what the server gives it, and what it gives back. The server knows only this
contract. Everything specific to a CLI lives in the harness's own folder.

## The folder

```
my-harness/
  harness.json     how it runs
  run.sh           the command, by default
  report.py …      any other files it needs; all of them are its scripts
  artifacts        the files it brings, and where they go (the shipped harnesses' convention)
```

`artifacts` is not part of the contract: the server never reads it. Every shipped `run.sh` reads
it and puts the files it lists in place ([bring artifacts](harnesses.md#configure-it-your-way)).

The PUT body for `/harnesses/{name}` is `harness.json` plus a `scripts` object, holding every
other file in the folder by name. `hi harness add ./my-harness` builds that body for you.

## harness.json

```json
{
  "name": "claude-code",
  "description": "Claude Code, headless.",
  "provider": "anthropic",
  "sandbox": "default",
  "files": {"AGENTS.md": "{instructions}"},
  "run": {
    "argv": ["bash", "{harness_dir}/run.sh"],
    "env": {"HOME": "{workspace}/.home"},
    "stdout": "application/x-ndjson",
    "timeout_s": 900
  }
}
```

| Field | Default | |
|---|---|---|
| `name` | required | lowercase letters, digits and dashes, starting with a letter or digit |
| `description` | `""` | free text |
| `provider` | required | the name of a provider; it must exist when the harness runs |
| `sandbox` | `default` | the name of a sandbox; it must exist when the harness runs |
| `files` | `{}` | path → content, written into the workspace before every run; both are [templated](#templates) |
| `run.argv` | `["bash", "{harness_dir}/run.sh"]` | the command, templated |
| `run.env` | `{}` | extra environment variables, templated, set alongside the contract's |
| `run.stdout` | `application/x-ndjson` | the content type of what the harness prints; `GET /responses/{id}/output` serves it as this |
| `run.timeout_s` | `900` | after this many seconds the run is killed, and recorded `incomplete` |
| `scripts` | `{}` | filename → content. Names must be plain filenames, with no `/` and no leading `.`. They are written to `{harness_dir}`, which Docker mounts read-only. |

## Templates

`files`, `run.argv` and `run.env` can use these placeholders:

| Placeholder | Is |
|---|---|
| `{task}` | the request's text |
| `{instructions}` | the request's `instructions` |
| `{model}` | the model after the `/` in `harness/model`, or empty |
| `{session_id}` | the session to resume, or empty |
| `{workspace}` | the workspace's path. In Docker it is mounted at the same path, so it is the same inside and out |
| `{harness_dir}` | the harness's scripts directory. In Docker it is mounted read-only, at the same path |
| `{provider_url}` | the provider's url |
| `{provider_key}` | the provider's key |

- Only `{identifier}` is a placeholder, so other braces, such as JSON or code, pass through.
- An unknown placeholder fails the request with a 400.

## What the harness gets

| | Where |
|---|---|
| the request, as JSON: `task`, `instructions`, `model`, `session_id`, `files` (their names), `metadata` | stdin, and the file at `HI_REQUEST` |
| the task | `HI_TASK` |
| the model | `HI_MODEL`, or empty |
| the session to resume | `HI_SESSION_ID`: what the previous turn reported, or empty on a first turn |
| the provider | `HI_PROVIDER_URL`, `HI_PROVIDER_KEY` |
| where things are | `HI_WORKSPACE`, `HI_HARNESS_DIR`, `HI_OUTPUT` |
| the way out, in Docker | `HTTPS_PROXY`, `HTTP_PROXY`, pointing at the egress door |
| the request's input files, and the harness's `files` | in the workspace, which is the working directory |

Reading stdin is optional: a harness that ignores it is fine.

## What the harness gives back

| | Where |
|---|---|
| its output | stdout, streamed to clients as it prints (`harness.output`) and kept byte for byte (`GET /responses/{id}/output`) |
| its log | stderr, streamed the same way (`harness.log`) and kept (`GET /responses/{id}/log`) |
| what the record reports | optional JSON written to the file at `HI_OUTPUT` (below) |
| its changes | whatever it adds, changes or deletes in the workspace: the record lists `files` and `deleted`, and `GET /responses/{id}/diff` shows them |

The `HI_OUTPUT` file holds a JSON object. Every key is optional:

| Key | Becomes |
|---|---|
| `answer` | the record's `output`: one assistant message with this text, if it isn't blank |
| `status` | `ok` or `fail`. Without it, exit code 0 is `ok`, and anything else `fail`. A timeout or a cancel decides first, whatever it says. |
| `session_id` | the resume handle; the next turn gets it as `HI_SESSION_ID`. Without it, the previous one is kept. |
| `usage` | the record's `usage`, as given, if it is an object |
| `cost_usd` | the record's `harness.cost_usd` |

## The rules of the workspace

- **One per conversation.** Every turn of a conversation runs in the same workspace, with the
  files as the last turn left them.
- **Internal paths are never produced files.** That covers `.hi/` (the server's own),
  `.home/`, `.git/` and `__pycache__/`. Set `"HOME": "{workspace}/.home"` so a CLI's own state
  survives between turns without being listed.
- **Changes are found with git:** each turn starts and ends with a commit, so its diff and its
  files can be read later, as it left them.
- **A `.gitignore` is the project's own.** The internal paths are ignored by the server
  separately, so a request or harness can add or replace `.gitignore` freely.
- **Owned by whoever runs in it.** In Docker that is uid 1000 when the server runs as root, and the
  server's own user otherwise, so the harness can always write to it.
