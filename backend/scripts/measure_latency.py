"""Measure the deployed API's latency on a sample clip (docs/plans/part-2-audio-and-deploy.md).

    uv run python scripts/measure_latency.py --api-url https://<api> --sample-id <id> [--runs 20]

Starts one job per run from the same sample clip, each with a different call date so the API's
deduplication never hands back an earlier job, polls each to the end, and prints the p50 and p95 of
every stage and of the whole job against the brief's 10-second target. `--json` also writes the
summary to a file. Stage times are the API's own (`latency_ms` of GET /jobs/{id}); `wall_ms` is the
time this script saw from the start request to the finished job, polling included.

The API allows 20 job starts an hour per client, so the default of 20 runs uses the whole budget.
"""

import argparse
import json
import math
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

TARGET_MS = 10_000
POLL_SECONDS = 1.0
MAX_POLLS = 150
STAGES = ("upload_ms", "transcribe_ms", "analyze_ms", "total_ms")


@dataclass(frozen=True)
class JobResult:
    ok: bool
    stages: dict[str, int] = field(default_factory=dict)
    wall_ms: int = 0
    error: str | None = None


def percentile(values: Sequence[float], p: int) -> float:
    """The nearest-rank percentile: the smallest value with p% of the values at or below it."""
    if not values:
        raise ValueError("no values to take a percentile of")
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return float(ordered[rank - 1])


def _error_code(response: httpx.Response) -> str:
    try:
        body = response.json()
        return str(body["error"]["code"])
    except (ValueError, KeyError, TypeError):
        return f"http_{response.status_code}"


def run_job(
    client: httpx.Client,
    sample_id: str,
    call_date: date,
    *,
    sleep: Callable[[float], None] = time.sleep,
    max_polls: int = MAX_POLLS,
) -> JobResult:
    started = time.perf_counter()

    def wall() -> int:
        return round((time.perf_counter() - started) * 1000)

    response = client.post(
        "/jobs", json={"sample_id": sample_id, "call_date": call_date.isoformat()}
    )
    if response.status_code != 202:
        return JobResult(ok=False, wall_ms=wall(), error=_error_code(response))
    job_id = response.json()["job_id"]
    for _ in range(max_polls):
        poll = client.get(f"/jobs/{job_id}")
        if poll.status_code != 200:
            return JobResult(ok=False, wall_ms=wall(), error=_error_code(poll))
        job: dict[str, Any] = poll.json()
        if job["status"] == "failed":
            return JobResult(ok=False, wall_ms=wall(), error=job.get("error_code") or "failed")
        if job["status"] == "done":
            stages = {k: v for k, v in job["latency_ms"].items() if k in STAGES and v is not None}
            return JobResult(ok=True, stages=stages, wall_ms=wall())
        sleep(POLL_SECONDS)
    return JobResult(ok=False, wall_ms=wall(), error="timeout")


def measure(
    client: httpx.Client,
    sample_id: str,
    *,
    runs: int,
    start: date,
    sleep: Callable[[float], None] = time.sleep,
) -> list[JobResult]:
    """One job per run, run after run, each on its own call date (counting back from `start`)."""
    return [run_job(client, sample_id, start - timedelta(days=i), sleep=sleep) for i in range(runs)]


def summarize(results: Sequence[JobResult]) -> dict[str, Any]:
    finished = [r for r in results if r.ok]
    columns: dict[str, list[float]] = {}
    for result in finished:
        for name, value in {**result.stages, "wall_ms": result.wall_ms}.items():
            columns.setdefault(name, []).append(float(value))
    return {
        "runs": len(results),
        "failed": len(results) - len(finished),
        "errors": dict(Counter(r.error for r in results if not r.ok and r.error)),
        "stages": {
            name: {"p50": percentile(values, 50), "p95": percentile(values, 95)}
            for name, values in columns.items()
        },
    }


def format_report(summary: dict[str, Any], *, target_ms: int = TARGET_MS) -> str:
    lines = [f"{summary['runs']} runs, {summary['failed']} failed"]
    for error, count in summary["errors"].items():
        lines.append(f"  {count} x {error}")
    lines.append(f"{'stage':<14}{'p50':>10}{'p95':>10}")
    for name, values in summary["stages"].items():
        lines.append(f"{name:<14}{values['p50'] / 1000:>8.1f} s{values['p95'] / 1000:>8.1f} s")
    total = summary["stages"].get("total_ms")
    if total is not None:
        verdict = "met" if total["p50"] <= target_ms else "not met"
        lines.append(f"{target_ms // 1000} s target: {verdict} (p50 of the API's own total)")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure the deployed API's latency on a sample clip."
    )
    parser.add_argument(
        "--api-url", required=True, help="the API's base address, from the stack output"
    )
    parser.add_argument("--sample-id", required=True, help="an id from GET /samples")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--json", type=Path, help="also write the summary here")
    args = parser.parse_args(argv)
    if args.runs < 1:
        print("--runs must be at least 1", file=sys.stderr)
        return 2

    with httpx.Client(base_url=args.api_url.rstrip("/"), timeout=30.0) as client:
        results = measure(client, args.sample_id, runs=args.runs, start=date.today())
    summary = summarize(results)
    print(format_report(summary))
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
