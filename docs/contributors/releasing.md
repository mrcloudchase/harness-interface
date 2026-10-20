# Releasing

A release is a `CHANGELOG.md` section merged to `main`. Nothing else creates a tag, and no one tags by
hand.

## Versions

The version is written once: the heading of the newest section of `CHANGELOG.md`, such as `## [2.0.0]`.
`pyproject.toml` reads it from there when the package is built. Versions are
[semantic](https://semver.org):

| Bump | When | For example |
|---|---|---|
| **major** | something that worked stops working | a route, field or setting removed or changed; a new contract version; the library's public API changed incompatibly |
| **minor** | something new, and everything that worked still does | a new route, field, runtime or shipped harness folder |
| **patch** | a fix, with nothing new | a bug fix; a shipped folder fixed, or its CLI's pin moved |

Harness folders written by others depend on the contract, so a change to what a folder is given or
gives back is a new contract version and a major release ([extending](extending.md#the-contract-is-versioned)).

## Cut a release

1. Add a section at the top of `CHANGELOG.md`, `## [X.Y.Z]`: the last version, bumped by the table.
   Under it, say what changed for a user, in their words.
2. If it touches a runtime, the contract, `hi_adapter.py`, the base image or a shipped folder, run the
   [live suite](testing.md#the-live-suite) for the folders it affects, and note the results in the PR.
3. Open the pull request, get CI green, and merge it.

A pull request that changes nothing a user sees, such as a test or a typo, adds no section. If another
release merges first, merge `main` in and take the next version.

On the push to `main`, [`release.yml`](../../.github/workflows/release.yml) does the rest:

```
newest CHANGELOG section ─► tagged already? ─ yes ─► nothing to do
                                   │ no
                                   ▼
                             its notes ─► the tests ─► uv build ─► gh release create vX.Y.Z
                                                                   (tag at the merged commit,
                                                                    the wheel and sdist,
                                                                    the section as its notes)
```

A failure at any step creates no tag.

## What users get

- **The installer** installs the latest release; `HI_REF` picks another tag, a branch or a commit.
- **The library**, pinned in a project:
  `uv add "harness-interface @ git+https://github.com/mrcloudchase/harness-interface@vX.Y.Z"`.
- **The release page** has the notes, and the wheel and sdist.

A change to `harness/base.Dockerfile` changes the base image's tag and every harness's install key, so
each harness installs once more on first use after the upgrade. Say so in the notes.

## When a release goes wrong

- **The workflow failed before tagging:** fix it on a branch and merge; the next push to `main`
  retries, or run the workflow by hand from the Actions tab.
- **A bad release is out:** don't move or delete its tag. Fix forward with a patch release; if it is
  harmful, mark the GitHub release as a pre-release so the installer's "latest" skips it.
