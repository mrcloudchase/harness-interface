# Vision

The owner's file: where harness-interface is going, and what it won't do.

## North star

harness-interface is the server that lets an organization run any coding harness as a service:
their providers, their sandboxes, their harness folders, their members' keys, one OpenAI Responses
request shape, stateful or stateless. It is hosted for orgs that sign up and self-hosted by orgs that
want their own, from the same code. It manages execution and tenancy, never the harness: a harness
is a folder the org owns, and what the harness prints is the answer.

## Principles

1. **Ship bare.** No harness folders, no loop engine, no console in the package. Templates in the
   docs show what an org adds; agents, loops and factories are programs against the API.
2. **The server never learns a CLI.** It copies seed files it does not read and relays output it
   does not parse. A new CLI is an upload, never a release.
3. **One request shape, standard.** The OpenAI Responses format, unchanged, so every client and SDK
   works on day one.
4. **Nothing of value in the sandbox.** Keys sealed at rest, opened per run, held only by that run's
   door; a fresh locked-down container per turn.
5. **A tenant is a prefix.** Isolation by construction, the same code for one org or a thousand.
6. **Simple enough to read.** Keep it simple, say each thing once, one job per module, objects for
   state, test first, and make what must never happen impossible.

## Themes

1. **The hosted platform:** sign-up creating orgs with the admin key, quotas and billing beside the
   server, cells of one server, one Docker host and one data directory each.
2. **Templates that stay true:** the documented folders pass `scripts/live.py` against the pinned
   CLI versions they name.
3. **Nothing added to the server for a harness.** A request to change the server for one CLI is a
   request to improve a folder.
