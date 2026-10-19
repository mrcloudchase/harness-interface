# Extending harness-interface

Each kind of change has one place to go. Find it here, change that layer, and nothing below it.
If a change seems to need two layers to know something new, the lower one is probably missing a
general idea. Add that, not the special case.

| You want to | Change | Not |
|---|---|---|
| support a new CLI | a folder in `harnesses/` | any Python |
| give a harness a tool or host | its sandbox (a Dockerfile, and `egress`) | the runtime |
| add a tool to every shipped harness's sandbox | `resources/default.Dockerfile` | |
| run things somewhere new (a VM, Kubernetes, a remote host) | a new `Runtime` in `runtimes/`, and a `Placement` | the harness contract or the platform |
| choose harnesses another way | a new `Router` in `routing.py` | the platform or the API |
| store resources or records somewhere else | a class with `JsonStore`'s four methods, built in `Registry` and `Service` | the registry's callers |
| give a harness something it doesn't get | its folder: `run.sh`, `files`, `artifacts`; or its sandbox | the contract, or a harness-specific branch anywhere |
| serve another wire format | a package beside `api/`, calling `Service`, given layer 7 in `tests/test_layers.py` | the platform |
| add a command to `hi` | `frontend/cli/hi_cli/` | the server |

## Add a harness

A harness is configuration, so adding one changes no platform code.
[Harnesses](../users/harnesses.md#write-your-own) shows how to write one, and the
[harness contract](../users/harness-contract.md) has every field and variable. To ship it with
harness-interface:

1. Add `harnesses/NAME/`: `harness.json`, `run.sh`, an `artifacts` file and, if its output
   needs translating, `report.py`. Copy a shipped harness that is close to yours: its `run.sh`
   opens with the lines that place artifacts, which every shipped harness shares word for word,
   and its `artifacts` file lists nothing.
2. Put the request's instructions where the CLI reads them, usually `AGENTS.md` through
   `files`, or a flag. Resume with `HI_SESSION_ID`, and report the session the CLI gives back.
3. If its CLI isn't in the default sandbox, add it to `resources/default.Dockerfile`, pinned to
   a version wherever its publisher allows. That changes the image's tag, so every user rebuilds
   once on upgrade.
4. Add a row to the table in [harnesses/README.md](../../harnesses/README.md), and its name to
   the list in the root README.
5. `test_every_shipped_harness_loads_and_prepares` checks it loads and prepares, and
   `test_every_shipped_harness_puts_dropped_artifacts_in_place` that it carries the shared
   artifacts lines and an `artifacts` file. The shipped harnesses are counted in that first test
   and in `test_pack_and_the_shipped_harnesses` in `test_cli.py`, so raise both counts. Run it
   live, two turns with instructions, as in [Testing](testing.md#live-checks).

## Add a runtime

A runtime implements `Runtime` from `execution.py`: `start(spec)` returns an `Execution`, and
`recover()` removes what a crash left. To write one:
- **Use `ProcessExecution` if anything runs as a local process,** even a client such as
  `docker run` or `ssh`. Pass `kill` and `cleanup` for what killing and cleaning up mean there.
- **Return `NeverStarted(reason)`** for anything that stops it starting. Raise only `Invalid`,
  for a spec it can never run.
- **Tear down on every path,** including a cancel while starting. Shield the teardown.
- **State its guarantees** in its module docstring, and test each one, including what it leaves
  behind after a cancel and a timeout.
- **Keep paths the same.** If it runs elsewhere, the workspace must appear at the same path, or
  everything above it would have to translate paths.

Then add a `Placement` in `platform/placement.py` that builds it for a resolved harness, and a
value for `HI_RUNTIME` in `api/config.py` and `app.build`.

## Add a router

A router implements `Router.route(model, conversation)` and returns a `Route`: the harness, and
the model to pass through. It decides only; it never runs, stores or resolves anything. Raise
`Invalid` for a request it can't route. Keep the rule that a continued conversation stays on its
harness: its workspace and session belong to that harness. Pass it to `Service(router=...)`; the
server builds its `Service` in `build` in `api/app.py`.

## The harness contract is closed

The execution layer doesn't care that it runs a harness. It gives a program its inputs and
returns its outputs, and that is all it can count on from any harness, now or in the future. So
the contract in `harness/contract.py` is fixed:
- **Nothing is added:** no new variable, placeholder, `harness.json` field or reported key.
- **Nothing is removed or repurposed:** shipped and third-party harnesses depend on all of it.

What a harness needs beyond that, it builds in its own folder from what it already gets: `run.sh`
maps the inputs onto its CLI, and `report.py` maps the CLI's output onto the report. A change that
seems to need the contract to know more about harnesses belongs in a harness folder or a sandbox.

## Add an endpoint

1. The behaviour goes in `Service` (or the registry), tested in `test_platform.py`.
2. The route goes in `api/app.py`: validate, call, shape the reply, nothing else. Refusals are
   `Invalid`, `NotFound` or `Conflict`, which become 400, 404 and 409.
3. Test it in `test_api.py`, and document it in [the API reference](../users/api.md).
4. For `hi`, add the call to `hi_cli/api.py` and the command to `hi_cli/main.py`, tested in
   `test_cli.py` and documented in [the CLI reference](../users/cli.md).

## Add a front end

A front end translates. It turns its wire format into an `Ask`, calls `Service.start`, and
shapes the `Record` and the `Run`'s events back into its format. `api/wire.py` is the model:
the Responses format is known there and nowhere else. A front end owns no state; the service owns
the turns, and any number of front ends can share one service.
