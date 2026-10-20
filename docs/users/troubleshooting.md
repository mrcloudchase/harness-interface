# Troubleshooting

## Where to look

| | |
|---|---|
| `harness.stderr` and `harness.stdout` on the response | what the CLI printed; a CLI says why it failed here |
| `error` on the response | `code` and `message` when it `failed` |
| `GET /harnesses/{name}` | the install's state and log |
| the server's terminal | its own log |
| `logs/` in the data directory | each response's `.stdout`, `.stderr` and `.door` (the egress door's decisions), and each image build |
| `tools/{name}-{key}.log` in the data directory | each install's full log |

## Starting

| You see | What to do |
|---|---|
| `install: git is required` | Install git, then run the installer again. |
| `harness-interface: command not found` | Open a new terminal; uv put it in `~/.local/bin`. |
| the server says git is missing | Install git: every workspace is tracked with it. |
| Docker errors on the first install | Start Docker. Or run with `HI_RUNTIME=local`, with no sandbox. |
| the port is in use | Set `HI_PORT`. |

## Requests

| You see | What it means | What to do |
|---|---|---|
| 400 `no provider for …` | nothing registered matches the harness's default URL and shape | Register one, or name one: `harness@provider`. |
| 400 `… speaks …, not …` | the provider serves a shape the harness's CLI doesn't | Use a provider in a shape it lists in `apis`. |
| 400 naming the install | the harness's install failed | `GET /harnesses/{name}` for the log; fix `install.sh`, and PUT the folder again. |
| 400 on `PUT /harnesses` | the folder isn't valid contract 1; every problem is named | Fix them. A changed `hi_adapter.py` is refused: copy the shipped one. |
| 409 | the session already has a response running | Interrupt it, stop it, or wait. |
| a request waits a few minutes | the first install, or the base image building, once | Wait; `GET /harnesses/{name}` shows `installing`. |

## Responses

| You see | What it means | What to do |
|---|---|---|
| `failed`, `harness_failed` | the harness ran and said it failed, or ended without saying | Read `harness.stderr`. Often a key without credit, or a model the provider doesn't serve. |
| `failed`, `failed_to_start` | it never ran: the install it waited on failed, or Docker couldn't start it | The message says why; an install's log is on `GET /harnesses/{name}`. |
| `incomplete` | it hit `run.timeout_s` and was stopped | Raise the timeout in `harness.json`, or split the task. |
| `cancelled` | it was stopped, or an interrupt replaced it | Continue the session with `previous_response_id`. |
| `failed`, `server_restarted` | the server restarted while it ran | Continue the session; its resume handle was kept. |
| `failed`, `internal_error` | a bug in harness-interface | Please [open an issue](https://github.com/mrcloudchase/harness-interface/issues) with the message. |
| the CLI can't reach a host | a sandbox reaches only its provider | Install what it fetches in `install.sh`, or list the host in `run.egress`. `logs/{id}.door` shows each refusal. |
| a steer seems ignored | a CLI takes it at its next safe point, after its current tool call | It lands then, or, if the response ends first, is sent again as the next response (`harness.undelivered` if it couldn't be). |
