# 0001. Automated versions with release-please

Date: 2026-10-22 · Status: Accepted

## Context

The project had a hand-set version (0.1.0) in `backend/pyproject.toml`, no tags and no changelog. Commit messages
already follow Conventional Commits, the backend is the only deployable unit, and the owner makes every merge, so
no bot may push to `main` directly. FlakeHunter solved the same problem with release-please.

`uv.lock` records the version of the project itself when `pyproject.toml` states it. release-please's `python`
release type updates `pyproject.toml`, `setup.py`, `setup.cfg` and `__init__.py`, but not `uv.lock`, so a release PR
that bumped `pyproject.toml` would leave the lockfile stale and `uv lock --check` (and `uv sync --locked` in CI)
would fail.

## Decision

Use release-please (a GitHub Action pinned to the v5.0.0 commit) in manifest mode with one version for the whole
repository and plain `vX.Y.Z` tags. It keeps a release PR open that bumps the version and writes `CHANGELOG.md`;
merging the PR creates the tag and a GitHub Release.

The version lives only in `commitment_tracker.__version__`. `pyproject.toml` declares it dynamic and hatch reads it
from `__init__.py`, so `uv.lock` no longer records it; release-please skips the dynamic `pyproject.toml` with a
warning and updates `__init__.py` through a generic extra file annotated `x-release-please-version`.

The OpenAPI document carries a separate API contract version (`API_VERSION`), changed by hand only when the request
or response shape changes, so a release doesn't regenerate `openapi.json` or the frontend client.

## Consequences

- Commit types now set version numbers, so `feat:` and `fix:` must describe user-visible changes; tooling and
  documentation use `chore:`, `ci:`, `build:` or `docs:`.
- The owner still makes every merge, including the release PR's. Other workflows run on the release PR only with a
  fine-grained `RELEASE_PLEASE_TOKEN`, a standing credential to renew.
- A tag deploys nothing; deployment arrives in Part 2.
- `backend/tests/test_release_config.py` keeps the manifest, `__version__` and the workflow's pin, permissions and
  token fallback from drifting.

## Alternatives considered

- **Bump `pyproject.toml` and update `uv.lock` in a workflow step after release-please runs.** Adds a shell step to
  the only job that holds a write token.
- **A generic TOML extra file targeting the project's entry in `uv.lock`.** release-please's docs don't show that its
  TOML updater can select one entry from an array of tables, and `uv lock` rewrites the file.
- **semantic-release or a version from `git describe`.** No reviewable release PR, or no changelog.
