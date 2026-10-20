# Harness contract (version 1)

The contract between the server and a harness folder: what the folder must contain, what a harness is
given, and what it gives back. It assumes only what is true of any program: it is installed, started
in a directory with files and an environment, reads input, writes output, and can be signalled. No
protocol, output format, language or provider is assumed; the folder translates its CLI into this.

It is written down in code in one place, `harness_interface/harness/contract.py`, and the folder rules
in `harness_interface/harness/folder.py`.

## The folder

| File | Required | |
|---|---|---|
| `harness.json` | yes | below |
| `install.sh` | yes | installs the CLI into `$HI_TOOLS` |
| `run.sh` | yes | runs the harness: `bash run.sh`, in the workspace |
| `adapter.py` | yes | drives the CLI (run by `run.sh`) |
| `hi_adapter.py` | yes | the shared plumbing, byte-identical to `harness_interface/harness/hi_adapter.py` |
| `home/` | no | config artifacts, copied into `$HOME` before every response |
| `workspace/` | no | work artifacts, copied into a new session's workspace |
| `image.Dockerfile` | no | starts `FROM hi-base`; built once, for OS packages `install.sh` can't add |

A folder holds plain files; links are refused. A folder whose `hi_adapter.py` differs from the
server's is refused.

## harness.json

A closed schema: an unknown or missing field is an error, and every problem is named at once.

```json
{
  "contract": 1,
  "name": "claude-code",
  "description": "Claude Code, headless over stream-json and steered mid-turn.",
  "provider": {"url": "https://api.anthropic.com", "api": "anthropic-messages"},
  "apis": ["anthropic-messages"],
  "install": {"egress": ["registry.npmjs.org"], "timeout_s": 900},
  "files": {".home/.claude/CLAUDE.md": "{instructions}"},
  "run": {"interrupt": "steered", "stdout": "application/x-ndjson", "timeout_s": 1800, "stop_timeout_s": 20,
          "credential": "gateway", "egress": []},
  "report": [".claude/projects/*/memory/**"]
}
```

| Field | Meaning |
|---|---|
| `contract` | `1`: the version this folder was written for. A server refuses a contract it doesn't know. |
| `name` | lowercase letters, digits and dashes, at most 63 |
| `description` | one line |
| `provider` | the default provider: `url` and `api`. `api` must be one of `apis`; `url` follows the rule below. |
| `apis` | the API shapes the harness speaks: `anthropic-messages`, `openai-responses`, `openai-chat` |
| `install.egress` | the hosts (`host` or `host:port`) `install.sh` may reach |
| `install.timeout_s` | the install's time limit |
| `files` | `{workspace path: template}`, rendered before every response. `{instructions}` is the request's instructions. An empty render deletes the file. Not under `.git/`. |
| `run.interrupt` | `steered`: later stdin lines reach the running work. `continued`: it stops gracefully and resumes. `responded`: neither. |
| `run.stdout` | the content type of what it prints, such as `application/x-ndjson` |
| `run.timeout_s` | a response's time limit; then it is stopped |
| `run.stop_timeout_s` | the time between a stop's SIGINT and the kill |
| `run.credential` | optional: `gateway` (the default) or `file`. See [security](security.md#keys). |
| `run.egress` | optional: hosts a session may reach besides its provider; none by default |
| `report` | optional: globs under `$HOME` (`*`, `?`, `**`) of files the harness writes that come back with each response |

**The provider URL** is the base URL the shape's official SDK takes, `https://` with no credentials,
query or fragment: for `anthropic-messages` without a version path (`https://api.anthropic.com`,
`https://api.deepseek.com/anthropic`), for `openai-*` with one (`https://api.openai.com/v1`,
`https://api.deepseek.com/v1`). The same rule holds for every provider registered with the server, so
an adapter never guesses.

## What a harness is given

| | |
|---|---|
| working directory | the session's workspace, at the same path inside the sandbox as outside |
| `HI_WORKSPACE` | that path |
| `HOME` | `$HI_WORKSPACE/.home`, kept for the whole session |
| `HI_HARNESS_DIR` | the folder, read-only |
| `HI_OUTPUT` | the result file's path, outside the workspace |
| `HI_MODEL` | the model the request named, or empty |
| `HI_PROVIDER_URL` | the provider's base URL, or under the gateway the gateway's URL with the same path |
| `HI_PROVIDER_API` | the provider's shape |
| `HI_PROVIDER_KEY_FILE` | a read-only file holding a session token (gateway) or the key (file mode) |
| `PATH` | `$HI_TOOLS/bin` first |
| `HTTPS_PROXY`, `NO_PROXY` | in the sandbox: the egress door, and loopback left unproxied |
| stdin, line 1 | `{"task": "…", "resume": "…" or null}`, one compact JSON line |
| stdin, later lines | one JSON string each: more text, for a `steered` harness |
| `$HOME` | the folder's `home/`, then `files`, copied in before every response |
| the workspace | the folder's `workspace/` when the session starts, then the request's files |

Nothing else of the server's environment. `install.sh` is given `HI_TOOLS` (where to install),
`HI_HARNESS_DIR`, and a scratch `HOME`; no provider, key or token.

## What it gives back

- **stdout and stderr**, streamed as they are written and kept byte for byte.
- **The workspace's changes:** every file it adds, changes or deletes outside `.home/`.
- **Reported artifacts:** the files under `$HOME` matching `report` that the response added, changed
  or deleted.
- **`$HI_OUTPUT`**, a JSON object, written atomically (to a temporary file, then renamed): early,
  with `"status": "running"` and `resume` as soon as it knows it, and again at the end:

  | Key | |
  |---|---|
  | `answer` | the answer, as text |
  | `status` | `running`, `ok`, `fail` or `stopped`: from the CLI's own events, never its exit code |
  | `resume` | the CLI's handle to continue this conversation; given back on line 1 next time |
  | `usage` | `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `reasoning_tokens`; others allowed |
  | `cost_usd` | the harness's own figure, if it has one |
  | `steers` | how many steer lines the CLI took |

  Every key is optional, and any other key comes back too, untouched.

A response cut off while its file still says `running` (or says nothing) ends `stopped` if it was
asked to stop and had a resume handle, otherwise failed.

## Control

- **stdin stays open** for the whole response. Its end means stop gracefully.
- **SIGINT** to the run's process group means stop gracefully. If it hasn't ended
  `run.stop_timeout_s` later, it is killed. `run.timeout_s` stops it the same way.
- **Interrupting a session** degrades by the harness's tier: an idle session is continued with the
  text; a running `steered` harness gets the text as a stdin line; otherwise the response is stopped
  and the session continued with the text (`continued`, or `responded`).
- **Steers it didn't take.** If `steers` is less than the lines sent, the rest arrived too late: when
  the response ends `ok` the server sends them, joined, as the next response; otherwise it reports
  them undelivered. Nothing is sent after a stop.

## The smallest harness

`harness.json`, an `install.sh` that installs nothing, and a `run.sh` that reads line 1 and writes
`{"answer": "…", "status": "ok"}` to `$HI_OUTPUT`. It is `responded`, with no resume, and it works.
