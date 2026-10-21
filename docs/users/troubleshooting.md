# Troubleshooting

**The response is `failed` with `error.code: server_error`.** The run could not be set up. The
message says why: the image could not be pulled or built, `install.sh` failed (the message ends with
its log), the sandbox or provider named does not exist, Docker is not reachable. Fix it and send
the request again; nothing of the session was changed.

**`failed` with `exit_status`.** `request.sh` exited non-zero. Its stderr is `output[1]`; the CLI's
own error is usually there. A provider that refused the token's shape, a missing flag, a CLI that
could not find its config.

**`incomplete`.** The turn hit `run.timeout_s`. Raise it in `harness.json`, or split the task.

**401 / 403 / 404.** Unknown key; a member's key on an owner's route; a thing that is not yours or
does not exist (another org's always reads as not existing).

**409.** The session is running a turn. Wait, steer it, or cancel it.

**The CLI cannot reach its provider.** It must call `HI_PROVIDER_URL` (or the variable
`provider_env.url` names) with the token; a CLI that insists on its vendor's hostname will be
refused by the door. The door's decisions are in the session directory's `door.log`.

**The install cannot download.** Its egress is `harness.json`'s `install.egress` plus the
sandbox's; add the registry host. Behind a TLS-intercepting proxy, set `HI_CA_FILE`.

**The steer did nothing.** The script must handle the signal (`trap … USR1`) and read
`$HI_DIR/interrupt`; a CLI running in the foreground of a bash script receives the signal only if
the script forwards it, which is why the template backgrounds it and `wait`s.

**Where are the logs?** `<data>/logs/` for image builds; the harness version's `tools/*.log` for
installs; the session directory for `door.log` and `trace.jsonl`; the server's stdout for requests.
