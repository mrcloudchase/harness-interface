# Steer and cancel

Two things can reach a running turn: more text, and a stop.

## Steer

```bash
curl -s -X POST https://hi.example.com/v1/sessions/sess_…/interrupt -H "Authorization: Bearer $KEY" \
  -H 'content-type: application/json' -d '{"input": "Stop. Use the existing helper instead of writing a new one."}'
```

The text is recorded on the running turn and on the trace, and the next worker heartbeat delivers
it: the worker writes it to the run directory as `$HI_DIR/interrupt` and sends the package's
`interrupt` signal (`SIGUSR1` by default) to `request.sh` alone, never to the CLI it started.
What happens then is the package's decision.

The catalog's packages share one behaviour: the trap reads the text, the running CLI call finishes,
and the text runs as the next message in the same conversation before the turn ends. So the
response to a steered turn is the CLI's answer to the steer, with everything the first message
did still in the workspace. A package whose CLI takes input mid-turn may hand the text over at
once instead.

Steering is refused with 409 when the session has no running turn or the turn has not been
claimed yet. The reply is the running response as it stands.

The console's session page shows a steer field while the session runs. [Demos](demos.md)
shows a steer landing on six harnesses.

## Cancel

```bash
curl -s -X POST https://hi.example.com/v1/responses/resp_…/cancel -H "Authorization: Bearer $KEY"
```

A queued turn ends at once. A running one is stopped: the worker sends `SIGTERM` to the
container, the runner forwards it to `request.sh`'s whole process group, and a kill follows if
nothing has exited after the package's `run.stop_timeout_s`. `response.sh` still runs, with
`HI_OUTCOME=cancelled`, so the package decides what a cancelled turn returns. The response's
status is `cancelled`, and the session goes on from the workspace as it was left.

The call waits for the turn to end and returns the final response.

## Timeouts

A turn is killed when it runs past the smaller of the package's `run.timeout_s` and the tenant's
`run_timeout_s` ceiling. The status is `incomplete`, and the response carries what `response.sh`
returned or, failing that, the stdout captured so far.

## What a steer is not

A steer does not stop the CLI. If the harness is running a long shell command, the command
runs to its end before the steer is answered. A cancel is the way to stop work now. Bringing back
the tiered interrupt of version 2, where a package declares whether a steer reaches the CLI
mid-turn, resumes it after a stop, or restarts it, is planned for a 4.x release.

Next: [Traces and captures](traces-and-captures.md).
