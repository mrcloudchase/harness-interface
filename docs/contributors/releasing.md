# Releasing

A release is a section in `CHANGELOG.md`. The newest section's heading is the version;
`pyproject.toml` reads it from there. Merging a new section to `main` runs the release workflow:
the suite, the wheel, the image pushed to GitHub's registry, a tag `vX.Y.Z` and a GitHub release
with the section as its notes. Nothing else creates tags.

The sandbox base image is built, scanned and published on a schedule by `base-image.yml`; set
`HI_BASE_IMAGE` on a fleet to the published reference.
