# For agents working in this repository

Read `docs/contributors/architecture.md` and `docs/users/security.md` before changing code. The
layer rule and the security invariants are tests; keep them green. Do not add a cloud SDK, an
orchestrator, a sandboxes resource, or a way for a tenant to choose an image or a limit. Keep the
public surface frozen within a major version. Docs are short sentences and tables.
