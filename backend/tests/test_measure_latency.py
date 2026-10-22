"""scripts/measure_latency.py against a fake API served by httpx's mock transport (no network)."""

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_latency.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("measure_latency", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["measure_latency"] = module
    spec.loader.exec_module(module)
    return module


script = load_script()
JOB = "a" * 64


class FakeApi:
    """A job that is `transcribing` for a few polls, then done with the stage times given."""

    def __init__(self, *, polls_until_done: int = 2, fail: str | None = None) -> None:
        self.polls_until_done = polls_until_done
        self.fail = fail
        self.posted: list[dict[str, Any]] = []
        self.polls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/jobs":
            self.posted.append(json.loads(request.content))
            return httpx.Response(202, json=self.job("transcribing"))
        if request.method == "GET" and request.url.path == f"/jobs/{JOB}":
            self.polls += 1
            done = self.polls >= self.polls_until_done
            if done and self.fail:
                return httpx.Response(200, json=self.job("failed", error_code=self.fail))
            return httpx.Response(200, json=self.job("done" if done else "analyzing"))
        return httpx.Response(404, json={"error": {"code": "job_not_found"}})

    @staticmethod
    def job(status: str, **extra: Any) -> dict[str, Any]:
        latency = {
            "upload_ms": None,
            "transcribe_ms": 15_400,
            "analyze_ms": 1_600,
            "total_ms": 17_300,
        }
        return {"job_id": JOB, "status": status, "latency_ms": latency, **extra}

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), base_url="http://api.test")


def no_wait(_: float) -> None:
    return None


# --- Percentiles ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "p", "expected"),
    [
        ([5.0], 50, 5.0),
        ([1.0, 2.0, 3.0, 4.0], 50, 2.0),
        ([1.0, 2.0, 3.0, 4.0], 95, 4.0),
        ([4.0, 1.0, 3.0, 2.0], 100, 4.0),
        (list(map(float, range(1, 21))), 50, 10.0),
        (list(map(float, range(1, 21))), 95, 19.0),
    ],
)
def test_percentile_is_the_nearest_rank(values: list[float], p: int, expected: float) -> None:
    assert script.percentile(values, p) == expected


def test_percentile_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError, match="no values"):
        script.percentile([], 50)


# --- One job -------------------------------------------------------------------------------------


def test_a_run_posts_the_sample_with_its_own_date_and_polls_to_the_end() -> None:
    api = FakeApi(polls_until_done=3)

    result = script.run_job(api.client(), "invoice", date(2026, 10, 21), sleep=no_wait)

    assert api.posted == [{"sample_id": "invoice", "call_date": "2026-10-21"}]
    assert api.polls == 3
    assert result.ok
    assert result.stages == {"transcribe_ms": 15_400, "analyze_ms": 1_600, "total_ms": 17_300}
    assert result.wall_ms >= 0


def test_a_failed_job_is_reported_with_its_code() -> None:
    result = script.run_job(
        FakeApi(fail="model_unavailable").client(), "x", date(2026, 10, 21), sleep=no_wait
    )
    assert not result.ok
    assert result.error == "model_unavailable"


def test_a_refused_start_is_reported_with_its_code() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": {"code": "rate_limited"}}, headers={"retry-after": "30"}
        )

    client = httpx.Client(transport=httpx.MockTransport(refuse), base_url="http://api.test")

    result = script.run_job(client, "x", date(2026, 10, 21), sleep=no_wait)

    assert (result.ok, result.error) == (False, "rate_limited")


def test_a_job_that_never_finishes_times_out() -> None:
    result = script.run_job(
        FakeApi(polls_until_done=10_000).client(),
        "x",
        date(2026, 10, 21),
        sleep=no_wait,
        max_polls=5,
    )
    assert (result.ok, result.error) == (False, "timeout")


# --- Many jobs -----------------------------------------------------------------------------------


def test_every_run_uses_a_different_call_date_so_none_is_deduplicated() -> None:
    api = FakeApi(polls_until_done=1)

    results = script.measure(
        api.client(), "invoice", runs=3, start=date(2026, 10, 21), sleep=no_wait
    )

    assert [r.ok for r in results] == [True, True, True]
    assert [p["call_date"] for p in api.posted] == ["2026-10-21", "2026-10-20", "2026-10-19"]


def test_the_summary_gives_p50_and_p95_of_each_stage_and_the_wall_clock() -> None:
    results = [
        script.JobResult(
            ok=True,
            stages={"transcribe_ms": 1000 * n, "analyze_ms": 100 * n, "total_ms": 1100 * n},
            wall_ms=1200 * n,
        )
        for n in range(1, 21)
    ]

    summary = script.summarize(results)

    assert summary["runs"] == 20
    assert summary["failed"] == 0
    assert summary["stages"]["total_ms"] == {"p50": 11_000.0, "p95": 20_900.0}
    assert summary["stages"]["transcribe_ms"]["p50"] == 10_000.0
    assert summary["stages"]["wall_ms"]["p95"] == 22_800.0


def test_failed_runs_are_counted_and_left_out_of_the_percentiles() -> None:
    good = script.JobResult(ok=True, stages={"total_ms": 10_000}, wall_ms=10_500)
    bad = script.JobResult(ok=False, error="timeout", wall_ms=150_000)

    summary = script.summarize([good, bad])

    assert (summary["runs"], summary["failed"]) == (2, 1)
    assert summary["stages"]["total_ms"] == {"p50": 10_000.0, "p95": 10_000.0}
    assert summary["errors"] == {"timeout": 1}


def test_with_nothing_finished_there_is_no_percentile_to_report() -> None:
    summary = script.summarize([script.JobResult(ok=False, error="rate_limited", wall_ms=10)])
    assert summary["stages"] == {}


def test_the_report_states_the_target_and_whether_it_was_met() -> None:
    results = [script.JobResult(ok=True, stages={"total_ms": 17_300}, wall_ms=17_900)]
    text = script.format_report(script.summarize(results), target_ms=10_000)
    assert "p50" in text
    assert "17.3 s" in text
    assert "10 s target: not met" in text

    quick = [script.JobResult(ok=True, stages={"total_ms": 8_000}, wall_ms=8_400)]
    assert "10 s target: met" in script.format_report(script.summarize(quick), target_ms=10_000)


def test_fewer_than_one_run_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    assert script.main(["--api-url", "http://api.test", "--sample-id", "x", "--runs", "0"]) == 2
    assert "--runs must be at least 1" in capsys.readouterr().err
