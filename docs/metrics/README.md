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

## Fleet runs, 13 to 15 November 2026

The first work done by the agent fleet (fleet-kit's control plane on one Linux machine): six issues, each by an
author agent in its own clone and session, each pull request reviewed by a separate reviewer agent. The
transcripts are the slots' own, under `/home/<slot>/.claude/projects` on the fleet machine.

| File | Contents |
| --- | --- |
| `fleet-2026-11-15.json` | The report as JSON, all slots together |
| `fleet-2026-11-15.md` | The same report as tables |
| `merged-prs-2026-11-15.json` | The merged PRs it was computed from |

Made on the fleet machine, as root because a slot's transcripts are readable only by the slot:

```bash
d=$(mktemp -d); for s in agent01 agent02 agent03 agent04 review01; do ln -s /home/$s/.claude/projects $d/$s; done
uv run --script /opt/fleet-kit/scripts/fleet_report.py --root $d --prs prs.json --since 2026-11-13 --json
```

The report's "Merged PRs" column for W46 (15) counts every PR merged in the repository that week. The fleet
merged six of them (#39, #43, #44, #49, #50, #51; 351 changed lines), and the figures below use those six.

### Against the baseline

| Measure | Baseline (W43 to W45) | Fleet (W46) |
| --- | --- | --- |
| Weighted tokens per merged PR | about 925,000 (25.9M over 28) | about 255,000 (1.53M over 6), reviews included |
| Weighted tokens per changed line | about 870 | about 4,350 |
| Changed lines per PR | about 1,060 | 59 |
| Median context per call | 92,500 to 171,000 | 26,500 |
| 90th percentile context | 101,000 to 567,000 | 43,400 |
| Calls at 150k context or more | 0% to 60% | 0% |
| First turn, cache read plus fresh write (median) | 72,000 to 84,000 | about 20,200 (11,400 + 8,800) |
| Cache reads | 94% to 98% | 92% |
| Cache expiry | 0% to 15% | 6% |

What it shows:

- **A PR costs about a quarter of what it did.** One task per session keeps the context small: no call reached
  150k, where 60% of W43's calls were.
- **Per line the fleet looks five times worse, and that is the size of the tasks, not the fleet.** Five of the
  six PRs changed 2 to 24 lines, and a session costs about 150k to 300k weighted tokens however small the
  change. The one PR of ordinary size, #44 (283 lines), cost 1,083 per line, within noise of the baseline's 870.
- **A quarter of the tokens (382k, the `HEAD` row) are the reviews**, which run on a detached commit. The
  baseline had no separate reviewer.
- **The first turn is smaller**, but the two medians are not the same thing: both include sub-agent
  transcripts, and a fleet session is headless, with two plugins and no claude.ai skills.

Caveats: six PRs over three days is a small sample, and the tasks were chosen to be small. The same caution as
for the baseline applies: treat changes under about 1.5x as noise. One run was wasted: the allocator handed out
issue 46 again seconds after its PR merged (about 26k weighted tokens).
