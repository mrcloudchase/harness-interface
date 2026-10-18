# Troubleshoot

## Where to look

| | |
|---|---|
| `hi log <id>` | the harness's stderr, where a CLI explains why it failed |
| `hi output <id>` | the harness's stdout, exactly as it printed it |
| `hi show <id>` | the record, including `error.code` and `error.message` |
| `hi server logs` | the server's own log |
| `~/.harness-interface/data/logs/build-*.log` | each sandbox image build |

## Install and startup

| You see | What to do |
|---|---|
| `install: git is required` | Install git (`apt install git`, `brew install git` or `xcode-select --install`), then run the installer again. |
| `hi: command not found` after installing | Open a new terminal; uv put `hi` in `~/.local/bin`. |
| `Docker is not installed` or `Docker is not reachable` from `hi server start` | Start Docker. Or run without it: `HI_RUNTIME=local hi server start` ([runtimes](configuration.md#runtimes)). |
| `git is required` from `hi server start` | Install git. |
| `hi: no server at http://127.0.0.1:8000` | Run `hi server start`. If the server runs elsewhere, set `HI_URL`. |
| the port is already in use | Pick another: `HI_PORT` for the server, and `HI_URL` for `hi`. |

## Runs

| You see | What it means | What to do |
|---|---|---|
| `hi run` shows nothing for minutes | the sandbox image is building, once | Wait. When the build ends, its log is in `~/.harness-interface/data/logs/`. |
| `failed`, `setup_failed` | the sandbox couldn't be set up, so the harness never ran: its image failed to build, or Docker couldn't start the run | The message has the end of the build log. Fix the Dockerfile, or check Docker. |
| `failed`, `harness_failed` | the harness ran and failed | `hi log <id>`. Often a wrong key, a model name the provider doesn't serve, or a missing provider setting. |
| `failed`, exit 127, on the local runtime | the harness's CLI isn't installed on this machine | Install it, or use the Docker runtime. |
| `incomplete` | the run hit its timeout, `run.timeout_s` in `harness.json` (900 s by default) | Raise the timeout, or split the task. |
| `failed`, `internal_error` | a bug in harness-interface, not the harness | The message says what failed. Please [open an issue](https://github.com/mrcloudchase/harness-interface/issues) with it. |
| `failed`, `server_restarted` | the server restarted while the run was going | Run it again. |
| a 409 on `hi run -c` | that conversation still has a run in progress | Wait for it, or `hi cancel` it. |
| a 400 naming a provider or sandbox | the harness names one that doesn't exist | Add it, or change the harness ([providers](providers.md), [sandboxes](sandboxes.md)). |
| a 400 `unknown placeholder` | a `{name}` in the harness's `files`, `env` or `argv` isn't one the server fills in | Use a [known placeholder](harness-contract.md#templates). |
| the harness can't reach a host | the sandbox allows only the provider's host | Add the host to the sandbox's `egress` ([sandboxes](sandboxes.md#allow-more-hosts)). |
