# Releasing

A release is a `CHANGELOG.md` section merged to `main`. The newest section's heading is the version
(`pyproject.toml` reads it from there); the release workflow tags `vX.Y.Z` when no such tag exists,
builds the package and publishes a GitHub release with the section as its notes.

Before merging a release: `uv run pytest`, `uv run pytest -m docker`, and `scripts/live.py` against
a server running the branch with at least one real harness.
