# Token baselines

Token use for this project, measured with fleet-kit's `scripts/fleet_report.py` from the Claude Code
transcripts in `~/.claude/projects/`. Claude Code deletes transcripts after 30 days by default, so these files
are the lasting record; later reports are compared against them.

## Baseline of 2026-11-11

Weeks 2026-W43 to W45 (21 Oct to 8 Nov 2026), before any fleet runs or practice changes.

| File | Contents |
| --- | --- |
| `baseline-2026-11-11.json` | The report as JSON (`--json`): one row per ISO week, top branches |
| `baseline-2026-11-11.md` | The same report as tables |
| `merged-prs-2026-11-11.json` | The merged PRs it was computed from (`gh pr list --state merged`) |

Made with:

```bash
gh pr list --state merged --limit 2000 --json number,headRefName,mergedAt,additions,deletions > prs.json
uv run --script scripts/fleet_report.py --prs prs.json --project commitment-tracker-ai \
  --baseline 2026-W43,2026-W44,2026-W45 --json
```

Totals match fleet-kit's `session_tokens.py` within 0.03% (783 against 784 calls).

## How to compare against it

Compare against the whole-period figure, **about 870 weighted tokens per changed line** (25.9M over 29.8k
lines), not the weekly index. W43 is 87% of the baseline's tokens, so the averaged index makes almost any later
week look several times better. Also compare median context, the share of calls at 150k tokens or more, and the
first-turn cache write.

Caveats:

- Small sample: 3 weeks, 23 sessions, 28 merged PRs. Treat changes under about 1.5x as noise.
- Per-PR and per-line figures overstate cost: work committed straight to `main` (about 2.6M weighted tokens) has
  tokens but no PR lines.
- "Over ceiling" in this version of the report means 150k tokens or more, the context ceiling hook's
  advisory level; later versions head the same column "Ctx >=150k" (JSON key `over_ceiling_share`).
- The first-turn medians include sub-agent transcripts, whose first turns are smaller than a main
  session's.

## What it showed

- One branch, `part3plan`, used about 60% of all tokens. In W43, 60% of calls were at 150k context or more,
  and the top tenth at 566k or more. Long sessions are the main cost; start a fresh session per task.
- Cache expiry was small (0–2% in full weeks), unlike the 31% Marquardt measured on idle sub-agents.
- The whole first prompt was 80–84k tokens, cached read plus fresh write. The rise in the fresh write
  (median 27k to 38k) was mostly fewer cache hits, not more content. The real growth, about 3k tokens, includes
  this repo's CLAUDE.md growing from 3.4k to 8.7k characters on 23 Oct.
- Every session's first message carries about 30k characters of skill listing and 5.3k of cc-practices
  SessionStart output, after the system prompt.
