# Vision

The owner's file: where harness-interface is going, and what it won't do.

## North star

harness-interface is the execution layer for coding harnesses. One request reaches any coding CLI, as a
session in its own sandbox, from an OpenAI Responses-compatible API or a Python library, so people can
build agents, loops and workflows on whichever harness fits. It manages execution, not harness
protocol: it sets up the sandbox, installs the CLI, brings its config and work artifacts, runs it,
steers and stops it, and returns everything it produced.

## Principles

1. **Harnesses live outside the server.** A harness is a folder: how to install the CLI, which config
   and work artifacts it brings, how to run, interrupt and stop it, and what to report back. The
   server has no code for any particular harness.
2. **A minimal, versioned contract.** Environment variables, stdin and one result file. It changes
   only as a new version, so a folder written today keeps working.
3. **Strict sandbox by default.** Every install and response runs locked down, reaching only what its
   folder names, and the provider's key never enters the sandbox.
4. **Configuration is something users bring.** Providers and harness folders are resources users put,
   changed with no restart. A different configuration is a different folder.
5. **Simple enough to read.** Keep it simple, say each thing once, one job per module, objects for
   state, test first, and make what must never happen impossible.

## Themes

1. **Every harness, always working:** each shipped folder passes the live suite, and a CLI update that
   breaks one is caught and fixed quickly.
2. **Any harness:** a new CLI is a folder, written from the contract and the survey, never a change to
   the server.
3. **Everything comes back:** every response returns the answer, the CLI's own output, the work's
   changes, the reported artifacts, usage and cost, streamed as it happens.
4. **Fast responses:** an installed harness starts in a second or two.
5. **A front end for people:** a command line that drives the server like an interactive harness CLI.

## Non-goals

- Translating harnesses into a common event schema or protocol.
- Keeping or merging state across sessions: a new session is a clean workspace.
- Spending caps enforced by the server; callers own their budgets.
- Authentication or multi-tenancy, for now.

## Constraints

- The library (layers 0 to 5) uses only Python's standard library.
- Python 3.11 and later; Linux and macOS; Docker for the sandbox.
