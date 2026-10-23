# Releasing

A release is a section of `CHANGELOG.md`. The newest section's heading is the version;
`pyproject.toml` reads it from there, and so does the release workflow.

1. Add a section `## [X.Y.Z]` at the top of the changelog with what changed, written for the
   people who run and use the platform.
2. Merge to `main`.
3. The release workflow sees that `vX.Y.Z` has no tag yet, runs the suite, builds the
   documentation and the wheel, builds the image, pushes
   `ghcr.io/mrcloudchase/harnessgatewayai:X.Y.Z` and `:latest`, tags the commit, and publishes
   a GitHub release with the wheel attached and the section as its notes.

Nothing else creates tags. A merge whose newest section is already tagged releases nothing.

## Versions

Major for a change to the public surface: a route, a body shape, the package contract, an
environment variable's meaning, the data layout. Minor for a new capability behind the same
surface. Patch for a fix.

## The base image

`.github/workflows/base-image.yml` builds the sandbox base image on a schedule, scans it, and
publishes it. A fleet points `HG_BASE_IMAGE` at the published reference so every worker runs the
same scanned image.
