# Releasing

A release is a `CHANGELOG.md` section merged to `main`. Nothing else creates a tag, and no one
tags by hand.

## Versions

The version is written once: the heading of the newest section of `CHANGELOG.md`, such as
`## [1.0.4]`. `pyproject.toml` reads it from there when the package is built, and `hi --version`
and the server's OpenAPI document read it from the installed package. Versions are
[semantic](https://semver.org):

| Bump | When | For example |
|---|---|---|
| **major** (`2.0.0`) | something that worked stops working | an endpoint, field, CLI flag or contract variable removed or changed; the public library API changed incompatibly |
| **minor** (`1.1.0`) | something new, and everything that worked still does | a new endpoint, field, command, runtime, or shipped harness |
| **patch** (`1.0.1`) | a fix, with nothing new | a bug fix; a harness's script fixed; a CLI in the default sandbox updated |

The harness contract is part of the public interface, and it is closed: nothing is added to it
([extending](extending.md#the-harness-contract-is-closed)), and since third-party harnesses
depend on it, removing or repurposing any of it would be a major version.

## Cut a release

Every pull request that changes behaviour is a release:
1. Add a section at the top of `CHANGELOG.md`, `## [X.Y.Z]`: the last version, bumped by the
   table above. Under it, say what changed for a user, in their words. `test_release.py` fails if
   the newest section's heading isn't a version, so CI catches it before the merge.
2. If it touches the Docker runtime, the contract, a shipped harness or the default sandbox, run
   the [live checks](testing.md#live-checks) and note them in the pull request.
3. Open the pull request, get CI green, and merge it.

A pull request that changes nothing a user sees, such as a test or a typo, adds no section. If
another release merges first, your section conflicts with its: merge `main` in and take the next
version.

On that push to `main`, [`release.yml`](../../.github/workflows/release.yml) does the rest:

```
newest CHANGELOG section ─► tagged already? ─ yes ─► nothing to do
                                   │ no
                                   ▼
                             its notes ─► the tests ─► uv build ─► gh release create vX.Y.Z
                                                                   (tag at the merged commit,
                                                                    the built wheel and sdist,
                                                                    the section as its notes)
```

Every other push to `main` finds its version already tagged and does nothing. A failure at any
step creates no tag.

## What users get

- **The installer** installs the latest release by default. `HI_REF` picks another tag, a branch or
  a commit.
- **The library**, pinned in a project:
  `uv add "harness-interface @ git+https://github.com/mrcloudchase/harness-interface@vX.Y.Z"`.
- **The release page** has the notes, and the wheel and sdist as assets.

A change to `resources/default.Dockerfile` changes the default sandbox's tag, so every user's
next run after upgrading builds the image once. Say so in the notes.

## The default sandbox's image

[`sandbox-image.yml`](../../.github/workflows/sandbox-image.yml) builds that image once and
publishes it to this repository's packages, under the name the server gives it plus the registry:
`ghcr.io/mrcloudchase/harness-interface/default:<hash>`. Something that runs harnesses on a fresh
machine, such as a CI job, pulls it and tags it `harness-interface/default:<hash>`; the server then
finds the image already there and builds nothing.

| When | It |
|---|---|
| a pull request changes the Dockerfile | builds it and runs its CLIs, to prove it builds |
| that change merges to `main` | builds and publishes it; when Keeper merges it, Keeper starts this workflow itself (`[publish]` in `keeper.toml`), since its merges start no workflows |
| someone runs it by hand | rebuilds and republishes it, with the latest release of the CLIs whose vendors' installers fetch one |

It builds the same way every time: its CLIs are pinned, and npm and uv resolve everything they
depend on as published by `RESOLVED_AS_OF`, a date in the Dockerfile that moves forward with the
pins (`scripts/latest_versions.py` lists each pin beside its latest release). Without it, a broken
release upstream breaks the build the hour it is published.

The image holds the CLIs and nothing secret. The build has an empty context, no build arguments
and no secret mounts, the registry login comes only after it, and the workflow fails if the image's
environment names a credential. A run gets its provider's key only when it starts, by name.

## When a release goes wrong

- **The workflow failed before tagging** (tests, build, missing notes): fix it on a branch and
  merge. The next push to `main` retries, or run the workflow by hand from the Actions tab
  (`workflow_dispatch`).
- **A bad release is out:** don't move or delete its tag, since installs and pins may already
  point at it. Fix forward with a patch release. If it is harmful, mark the GitHub release as a
  pre-release so the installer's "latest" skips it, and say why in its notes.
