# Extending

Where each kind of change goes. If a change seems to need two layers to learn something new, the lower
one is missing a general idea: add that, not a special case.

| You want to | Change | Not |
|---|---|---|
| support a new CLI | a folder in `harnesses/` | any Python |
| give a CLI a tool, a skill or a setting | its folder: `install.sh`, `home/`, `files` | the server |
| give a CLI an operating-system package | its folder's `image.Dockerfile` (`FROM hi-base`) | the base image |
| let a CLI reach another host | its folder's `run.egress` | the runtime |
| change what every harness starts from | `harness/base.Dockerfile`, pinned | |
| run somewhere new | a `Runtime` in `runtimes/`, and `Placement` | the contract or sessions |
| serve another wire format | a package beside `api/`, calling `Sessions` | sessions |
| change what a harness is given or gives back | a new contract version, with every folder | a harness-specific branch |

## Add a harness

A harness is a folder; the steps are in [harness folders](../users/harnesses.md#write-one) and every
field in the [contract](../users/harness-contract.md). To ship one in `harnesses/`:

1. Start from `harnesses/template`, and the CLI's page in the [survey](harness-survey/README.md).
2. Pin the CLI's version in `install.sh`; install everything it fetches at run time there.
3. Put one `hi-live-…` skill, MCP server and hook in `home/`, where the CLI reads them, so the live
   suite can prove it loads its config.
4. Pass the [live suite](testing.md#the-live-suite) in all four combinations.
5. Add it to the table in `harnesses/README.md`, and to the list in `README.md`.

`hi_adapter.py` is copied unchanged. A CLI that needs something it lacks gets it in its own
`adapter.py`; a need every adapter shares goes in the canonical copy and every folder's, in one commit.

## The contract is versioned

Contract 1 is environment variables, stdin and one result file, with a closed `harness.json`. Nothing
is added to it in place: a folder written for contract 1 must keep working. A harness that needs more
builds it in its own folder from what it gets. A change that truly needs the contract to change is
contract 2: `"contract": 2` in `harness.json`, every shipped folder moved, and a major version.

## Add a runtime

A runtime implements `execution.Runtime`: `start(spec)` returns an `Execution` that yields events, takes
input, stops, kills, and ends in one `Outcome`; a failure to start is a `NeverStarted`, not an
exception. Spawn processes through `runtimes/process.py`. Say in the module docstring what it
guarantees, prove each guarantee in its own suite, and give `Placement` a way to choose it. Nothing
above layer 1 should change.

## Add a front end

A front end turns its wire format into `Ask`s and calls `Sessions`; it shapes records, artifacts and
events back. `api/wire.py` is the only module that knows the Responses format. Another format is a
package beside `api/`, with its own wire module.
