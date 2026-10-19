# Vision

The human owner's file. Keeper turns it into work; only the owner changes it.

## North star

harness-interface is the execution layer for coding harnesses. One request reaches any harness,
from `hi`, an OpenAI Responses-compatible API or a Python library, so people can build agents,
loops and workflows on whichever harness fits, every run sandboxed and recorded. It manages
execution, not harness protocol.

## Principles

1. **Harnesses live outside the server.** A harness is a folder users set up to run their way; the
   shipped ones are templates. The server has no code for any particular harness.
2. **Agnostic, with a closed contract.** The execution layer doesn't care that it runs a harness: it
   gives a program its inputs and returns its outputs, streamed or not. The contract is never
   extended, so any harness, today's or tomorrow's, fits.
3. **Harness configuration is infrastructure users bring.** Providers, sandboxes and harnesses are
   resources users own, separate from the server, changed with no restart.
4. **Strict sandbox by default, overridable.** Every run is locked down with egress to its provider
   only, unless the user's sandbox allows more.
5. **Simple enough to read.** Keep it simple, say each thing once, one job per module, objects for
   state, and make what must never happen impossible. The library stays near 2,000 lines.

## Themes

1. **Every harness, always working**: all shipped harnesses pass two live turns with instructions
   every night, and a CLI update that breaks one is caught and fixed within a day.
2. **Runs anywhere**: it installs and runs cleanly as root, in containers and in CI, with clear
   errors when something is missing.
3. **Fast first run**: a run starts in seconds even on a new machine, without building a 10 GB image.
4. **Honest reporting**: every harness reports its answer, session, usage and cost as fully as its
   CLI allows, and the docs say exactly what each reports.
5. **A project that runs itself**: Keeper builds and maintains this repository from this file, and
   the owner's weekly hour is enough.

## Non-goals

- Translating harnesses into a common event schema or protocol.
- Adding to the harness contract.
- Spending caps or budgets enforced by the server; loops own their budgets.
- Per-request overrides of a harness's configuration; a different configuration is a different harness.
- Authentication or multi-tenancy, for now.

## Constraints

- The library (layers 0 to 6) uses only Python's standard library.
- Python 3.11 and later; Linux and macOS.
- Keeper's budget: $40 a day, $200 a week.
