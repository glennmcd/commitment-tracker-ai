# Releasing

Version numbers come from [release-please](https://github.com/googleapis/release-please). It reads the
Conventional Commit messages on `main`, keeps one **release PR** open that bumps the version and writes
`CHANGELOG.md`, and tags the release when you merge that PR. The reasoning is in
[ADR 0001](decisions/0001-release-please.md).

## How a release happens

1. Commits land on `main` as usual, directly or through squash-merged PRs.
2. The `release-please` workflow (`.github/workflows/release-please.yml`) opens or updates a PR titled
   `chore(main): release X.Y.Z`. It changes only `CHANGELOG.md`, `.release-please-manifest.json` and
   `backend/src/commitment_tracker/__init__.py`.
3. When you want to release, review that PR and merge it. release-please then creates the tag `vX.Y.Z` and a
   GitHub Release.

A release is a label on a commit. It deploys nothing.

## What decides the next version

The commit **type** does. Choose it for what changes for people who use the service or its API, not for which
files you touched.

| Commit | Effect while the version is 0.x | After 1.0.0 |
| --- | --- | --- |
| `fix:` | patch (0.2.0 → 0.2.1) | patch |
| `feat:` | minor (0.2.1 → 0.3.0) | minor |
| `feat!:`, `fix!:` or a `BREAKING CHANGE:` footer | minor | major |
| `docs:`, `chore:`, `ci:`, `test:`, `refactor:`, `build:`, `style:` | no release on their own | same |

A documentation-only change is `docs:` however large it is. When PRs are used, squash-merge them with the PR title
as the commit message: a merge commit would make release-please count the PR twice.

## Where the version lives

- `commitment_tracker.__version__` in `backend/src/commitment_tracker/__init__.py` is the only copy in the code.
  `backend/pyproject.toml` reads it (`dynamic = ["version"]`), so `uv.lock` doesn't record it and a release can't
  leave the lockfile stale.
- `.release-please-manifest.json` holds the last released version for release-please.
- `openapi.json` carries a separate **API contract version**, `API_VERSION` in
  `backend/src/commitment_tracker/api/app.py`. Releases don't change it. Bump it by hand, in the same commit, when
  the request or response shape changes, and regenerate `openapi.json` with `uv run export-openapi`.

Never edit `__version__` or the manifest by hand: the release PR changes them together, and
`backend/tests/test_release_config.py` fails if they disagree.

## One-time setup on GitHub

These change repository settings, so the owner does them.

1. **Let Actions open PRs.** In the repository's **Settings → Actions → General → Workflow permissions**, tick
   **Allow GitHub Actions to create and approve pull requests**. Without it the workflow fails when it tries to open
   the release PR.
2. **Optional: a token so other workflows run on the release PR.** PRs opened with the built-in `GITHUB_TOKEN` don't
   start other workflows. To have CI run on release PRs once CI exists, create a fine-grained personal access token
   for this repository only, with **Contents**, **Pull requests** and **Issues** set to read and write and an expiry
   date, and save it as the repository secret `RELEASE_PLEASE_TOKEN`. Without the secret the workflow uses the
   built-in token.

The workflow runs only on pushes to `main`, never for pull requests from forks. Its single step is the Action pinned
to a commit, with no shell commands; the tests fail if that changes or if it asks for more permissions.

## The first release

`bootstrap-sha` in `release-please-config.json` points at the repository's first commit, so the first changelog
lists the Part 1 work. The manifest starts at 0.1.0, and the `feat:` commits since then make the first release
0.2.0. Once that release PR is merged, release-please ignores `bootstrap-sha`.

To choose a version yourself, for example to declare 1.0.0, add a commit whose body ends with `Release-As`:

```bash
git commit --allow-empty -m "chore: release 1.0.0" -m "Release-As: 1.0.0"
```

## Updating the Action

Find the commit for a new release tag, check its inputs in its `action.yml`, and replace the commit and the
`# vX.Y.Z` comment in the workflow together:

```bash
gh api repos/googleapis/release-please-action/git/ref/tags/<tag> --jq .object.sha
```
