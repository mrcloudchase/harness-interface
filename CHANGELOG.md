# Changelog

Every release has a section here; the release workflow publishes it as the release's notes. Add
to "Unreleased" as you change things, and rename it to the version when you bump it.

## [Unreleased]

- **The harness guide says what a harness is, and whose choices it holds:** three files, and every
  CLI setting (permissions, MCP servers, skills, hooks) is the harness author's to configure.

## [1.0.2]

- **Docs checked line by line against the code,** and corrected wherever they had drifted.
- **How it works,** a new page for users: who owns what, the words, the three ways in, and when
  it fits. The README is shorter, and points to it.
- **The default sandbox drops its leftover `HOME` and `WORKDIR`.** Runs work at the workspace's
  own path and every harness sets its own `HOME`, so the image no longer sets either. Its tag
  changes, so the first run after upgrading builds it once.
- **The installer runs on Python 3.13,** a version CI tests; CI now also tests 3.14. The minimum
  stays 3.11.
- **The license names its copyright holder.**

## [1.0.1]

- **OpenHands follows the request's instructions.** It reads `AGENTS.md` only as untrusted
  context for code style, so a model such as Claude ignored a role or rule given there. Its harness
  now puts the instructions ahead of the task.
- **The CI badge** in the README renders everywhere, the GitHub mobile app included.

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
