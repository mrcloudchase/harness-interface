# Changelog

Every release has a section here; the release workflow publishes it as the release's notes. Add
to "Unreleased" as you change things, and rename it to the version when you bump it.

## [1.0.0]

The first release. harness-interface runs any harness in a sandbox, as a Python library and as an
OpenAI Responses-compatible server, with `hi`, its command line.

- **The library:** run a harness folder from Python with `Turn`, on Docker or locally, with no
  server and no dependencies beyond the standard library and git.
- **The server:** one API for every harness. `model` names the harness, `previous_response_id`
  continues its conversation, and its own output streams back. Runs belong to the server: they
  run side by side, outlive their clients, and can be cancelled at any point.
- **Sandboxed by default:** every run in a fresh container with no capabilities, a read-only root,
  and one way out, to its provider.
- **See everything:** stdout and stderr live; every file added, changed or deleted; each turn's
  diff and files as it left them, even mid-run.
- **23 harnesses ship with it**, each passing the request's instructions to its CLI.
- **Built in layers:** execution, runtimes, workspace, harness contract, resources, routing,
  platform, front end, each importing only those below it, enforced by tests.
