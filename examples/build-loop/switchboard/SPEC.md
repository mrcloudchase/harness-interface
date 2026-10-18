# switchboard

A small HTTP API server that runs command-line coding tools ("harnesses") by name. You register
a harness as a command; you start a run by naming the harness and giving it a task; the server
runs the command, records what happened, and lets a later run continue an earlier one.

Build it in Python with FastAPI. The app object is `app` in `switchboard/app.py`, so the tests
can do `from switchboard.app import app`. Keep everything in memory: no database, no files.

## Harnesses

A harness is `{"name": str, "command": [str, ...], "timeout_s": number}`.

- `name`: lowercase letters, digits and dashes, starting with a letter or digit.
- `command`: the argv to run, e.g. `["sh", "-c", "echo $TASK"]`. Must not be empty.
- `timeout_s`: optional, default 30.

| Method | Path | Behaviour |
|---|---|---|
| PUT | `/harnesses/{name}` | add or replace; 200 with the harness. 400 if the body's `name` differs from the path. 422 if the body is invalid (bad name, empty command). |
| GET | `/harnesses` | 200, the list, sorted by name |
| GET | `/harnesses/{name}` | 200, or 404 |
| DELETE | `/harnesses/{name}` | 200 `{"deleted": true}`, or 200 `{"deleted": false}` if it wasn't there |

## Runs

`POST /runs` with `{"harness": str, "task": str, "previous_run_id": str | null}` runs the
harness's command, waits for it, and answers 200 with the run:

```json
{"id": "run_…", "harness": "echo", "task": "hi", "status": "completed",
 "exit_code": 0, "output": "…stdout…", "log": "…stderr…", "previous_run_id": null}
```

- The command gets the task three ways: on stdin, as the `TASK` environment variable, and as
  `SWITCHBOARD_TASK`.
- `status` is `completed` if the exit code is 0, `failed` otherwise, and `timeout` if it ran past
  `timeout_s` (it is killed; `exit_code` is then null).
- `id` is unique, and starts with `run_`.
- 400 if the harness doesn't exist, or the task is empty or only whitespace.

Continuing: with `previous_run_id`, the command also gets `PREVIOUS_OUTPUT`, the previous run's
`output`. 400 if that run doesn't exist, or belongs to another harness.

| Method | Path | Behaviour |
|---|---|---|
| GET | `/runs` | 200, every run, oldest first |
| GET | `/runs/{id}` | 200, or 404 |
