# Releasing

A release is a version bump merged to `main`. Nothing else creates a tag, and no one tags by hand.

## Versions

The version is written once, in `pyproject.toml`. `hi --version` and the server's OpenAPI document
read it from the installed package. Versions are [semantic](https://semver.org):

| Bump | When | For example |
|---|---|---|
| **major** (`2.0.0`) | something that worked stops working | an endpoint, field, CLI flag or contract variable removed or changed; the public library API changed incompatibly |
| **minor** (`1.1.0`) | something new, and everything that worked still does | a new endpoint, field, command, runtime, or shipped harness |
| **patch** (`1.0.1`) | a fix, with nothing new | a bug fix; a harness's script fixed; a CLI in the default sandbox updated |

The harness contract is part of the public interface, and it is closed: nothing is added to it
([extending](extending.md#the-harness-contract-is-closed)), and since third-party harnesses
depend on it, removing or repurposing any of it would be a major version.

## Changes as they land

Every pull request that changes behaviour adds a line to `CHANGELOG.md` under `## [Unreleased]`,
saying what changed for a user, in their words.

## Cut a release

1. On a branch, set `version` in `pyproject.toml`, and rename `## [Unreleased]` in
   `CHANGELOG.md` to `## [X.Y.Z]`. `test_release.py` fails if the two disagree, so CI catches it
   before the merge.
2. For a release that touches the Docker runtime, the contract, a shipped harness or the default
   sandbox, run the [live checks](testing.md#live-checks) and note them in the pull request.
3. Open the pull request, get CI green, and merge it.

On that push to `main`, [`release.yml`](../../.github/workflows/release.yml) does the rest:

```
version in pyproject.toml ─► tagged already? ─ yes ─► nothing to do
                                   │ no
                                   ▼
              its CHANGELOG section ─► the tests ─► uv build ─► gh release create vX.Y.Z
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

## When a release goes wrong

- **The workflow failed before tagging** (tests, build, missing notes): fix it on a branch and
  merge. The next push to `main` retries, or run the workflow by hand from the Actions tab
  (`workflow_dispatch`).
- **A bad release is out:** don't move or delete its tag, since installs and pins may already
  point at it. Fix forward with a patch release. If it is harmful, mark the GitHub release as a
  pre-release so the installer's "latest" skips it, and say why in its notes.
