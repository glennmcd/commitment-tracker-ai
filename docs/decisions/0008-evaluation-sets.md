# 0008. Named, hashed evaluation sets

Date: 2026-10-23 · Status: Accepted

## Context

Part 1 evaluated one file, `eval/data/dev.jsonl`: 24 items that prompt v1 was tuned on. A score on it shows the
pipeline works, not how accurate it is. Part 3 needs a tuning set, a held-out headline set, audio items and a place
for imported drafts, and every report must say exactly which version of which set it ran on, so the gate can tell a
regression from a changed set.

## Decision

- **Layout.** Each set lives in `backend/eval/sets/<name>/` as `items.jsonl` plus `set.json`, a manifest with the
  name, a one-line description, a role (`dev`, `test` or `staging`), whether it is gated, and the batches its items
  came from (provenance, generation prompt version, call date, import and promote dates, item count).
- **Sets.** `dev` (50 items, the only set prompts may be tuned on), `test` (150 held-out items, gated, the
  headline), `audio` (30 clips that point at `test` ids, ADR 0010) and `staging/<batch>` (imported drafts, never
  scored in headlines or gated).
- **Item fields.** `EvalItem` gains a required `provenance` (`spec`, `hand-written` or `<family>-<model>`) and a
  required `review` (`unreviewed`, `accepted`, `edited`). `extra="forbid"` stays. Only `staging` sets may hold
  `unreviewed` items.
- **Hash.** A set's hash is the SHA-256 of its items in canonical form: each item re-serialised with sorted keys
  and compact separators, joined with `\n`. `.gitattributes` also pins `backend/eval/** text eol=lf`.
- **Reports pin the set.** Reports record the set name, hash and item count, are written to
  `eval/reports/<set>/`, and break scores down by provenance. `--data` runs go to `eval/reports/adhoc/`.
- **Migration.** `dev.jsonl` moves to `eval/sets/dev/items.jsonl` with `provenance: spec` and `review: accepted`.
  The existing Haiku report moves to `eval/reports/dev/` unchanged and is treated as a legacy run with no set hash.
  `uv run eval --data <file>` keeps working; `--set dev` is the default.
- **Leak test.** A test fails if a transcript appears in more than one set (`audio` excepted), if an id appears in
  two sets, or if any turn of six or more words from a non-dev item appears in an extractor prompt file.

## Consequences

- **Reproducible scores.** A report names the exact items it ran on, so two reports are comparable only when their
  hashes match, and the gate can demand a new baseline when a gated set changes.
- **Cross-platform hashes.** Hashing the canonical form means a Windows checkout with `core.autocrlf` and CI's
  Linux checkout agree, and reformatting a file doesn't change its hash.
- **Every edit to `test` is deliberate.** Promoting a batch changes the hash, so it needs a fresh report and
  baseline (ADR 0012).
- **One legacy report.** The Part 1 report has no set hash; the site labels it and the gate ignores it.

## Alternatives considered

- **Hash the raw file bytes.** Simpler, but line endings and key order would change the hash without changing a
  single item.
- **One file with a `split` field per item.** Fewer files, but no per-set manifest, and a typo in a split name
  would silently move an item between tuning and held-out data.
- **Keep sets outside git (a bucket or a dataset hub).** Hides changes from review and from the gate; the items are
  small text and belong next to the code that scores them.
