# Changelog

Every release is a section here, newest first, and the newest section's heading is the version.
A merge to `main` that adds a section releases it: the release workflow tags that version and
publishes the section as its notes.

## [1.0.5]

- **The default sandbox builds the same way every time.** Its CLIs were pinned, but what they
  depend on floated, so a release published upstream an hour earlier could break the build (one
  did: a package that requires a version its publisher never released). npm and uv now resolve
  every dependency as published by one date, `RESOLVED_AS_OF` in the Dockerfile, which moves
  forward with the pins. The image's tag changes, so the first run after upgrading builds it once.
- **The image is published.** `sandbox-image.yml` builds it once per Dockerfile and publishes it to
  this repository's packages, so a fresh machine can pull it instead of building it.

## [1.0.4]

- **AGENTS.md** gives anyone changing the code, person or coding agent, the founding principles,
  the layers, the flow of a turn, the rules that always hold and where each change goes.
- **The harness contract is closed.** The server assumes only that a harness takes input and
  returns output, so nothing is added to the contract; a harness builds anything more in its own
  folder. The contributor docs now say so.
- **A changelog section is a release.** The version is written only in `CHANGELOG.md`, as its
  newest section's heading; a merge that adds a section tags and publishes it, with no separate
  version bump.

## [1.0.3]

- **Bring artifacts to any harness.** Drop files in a harness's folder and list them in its
  `artifacts` file, which every shipped folder has, listing nothing; every shipped `run.sh` puts
  them under the CLI's home before each turn. Skills, settings, MCP servers, hooks: whatever that
  CLI reads, with no server change.
- **The harness guide says what a harness is, and whose choices it holds:** three files, and every
  CLI setting (permissions, MCP servers, skills, hooks) is the harness author's to configure.
- **Every shipped harness is a template you can read.** Each `run.sh` now explains every setting
  its `harness.json` makes, and `harnesses/README.md` says how to make one your own. Gajae drops a
  setting that repeated another.

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
