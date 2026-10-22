# Conventions

- **One concept per module, named for it**, and a docstring that opens with its layer and that one
  responsibility. If a change to one module needs a change to a module above it, the boundary is wrong.
- **Interfaces are protocols with two implementations and one shared test.** `Records` (SQLite,
  Postgres) and `Blobs` (directory, S3) run the same test file by fixture. No third implementation
  without a customer.
- **Refuse by name, early, at the edge.** Validation lives in `store.py`, `harness.py` and `wire.py`
  with messages that say what was wrong. Lower layers assert nothing about input and never guard with
  `assert`.
- **Prefer a setting to a feature and a ceiling to a policy.** Deployer knobs are `HI_*` variables read
  once into `Settings`; tenant ceilings are a `Limits` on the tenant record. No plan logic in the engine.
- **Nothing cloud-named.** `test_layers.py` fails on a cloud SDK outside `blobs.py` and `records.py`.
- **The public surface is frozen within a major version**: the Responses API, the package contract, the
  folder format, the `HI_*` variables a package sees.
- **Short sentences in docs, a table for parallel facts, no marketing.** A docstring says what the
  code guarantees, not what it hopes.
- **Deliberately absent**: a sandboxes or environments resource, image or Dockerfile uploads, a
  registry client, per-request limits, an adapter layer over harness output, an orchestrator, a
  third backend, a second edition.
