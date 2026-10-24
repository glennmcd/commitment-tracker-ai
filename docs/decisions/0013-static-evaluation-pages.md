# 0013. Static evaluation pages built from committed reports

Date: 2026-10-23 · Status: Accepted

## Context

Reviewers and hiring managers should be able to see the evaluation results, inspect individual items and compare
runs without the demo password. The site is a Next.js static export behind `PasswordGate` on its home page, with
no server code. The reports and sets are committed, so the data already exists at build time.

## Decision

- **Routes.** `/evals` (results tables and the list of sets), `/evals/runs/[run]` (scores, per-label table,
  confusion matrix, field accuracy, scores by provenance, failed items and run details),
  `/evals/runs/[run]/items` (items with expected and predicted spans side by side, filterable) and
  `/evals/compare` (two runs on one set, chosen client-side and kept in the query string).
- **Data.** `uv run eval-export-site` reads `eval/sets/` and `eval/reports/` (not `adhoc/`) and writes
  deterministic JSON under `frontend/src/data/evals/`. The output is committed, the pages import it at build time,
  and the backend CI job fails when it is stale.
- **No password.** The pages never render `PasswordGate` and call no API. The home page and the README link to
  them.
- **Accessibility.** The confusion matrix is a real table with every count shown; shading only supplements the
  numbers. Right and wrong are marked by text and an icon, controls are native, and the pages work on a phone.
- **No new dependencies.** Plain CSS for the matrix and score bars.
- **Tests.** Vitest component tests against fixture reports and one Playwright test that opens a run and an item.

## Consequences

- **Always in sync.** The pages show exactly the committed reports; the staleness check stops them drifting.
- **No runtime cost or attack surface.** The pages are static files with no API calls.
- **Public results.** Test transcripts and model outputs are public on the site, as they already are in the
  repository. The pages carry `noindex`.
- **Read-only.** Editing items stays in the terminal review tool.

## Alternatives considered

- **Fetch reports at run time from the repository or a bucket.** Avoids committing the export, but adds a runtime
  dependency and can show reports the build wasn't tested against.
- **A separate dashboard tool or notebook.** Quicker to build, but outside the site the README links to, and
  harder to keep in sync.
- **Put the pages behind the password.** Simpler, but they hold nothing worth protecting and the audience is
  people without the password.
