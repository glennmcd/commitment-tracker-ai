"""CloudWatch metrics through the embedded metric format: one JSON line per data point."""

import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest

from commitment_tracker.api.app import build_spend_cap
from commitment_tracker.guardrails import metrics
from commitment_tracker.guardrails.spend import MemorySpendStore, SpendCap
from commitment_tracker.settings import Settings

NOON = 1_761_048_000.0  # 2025-10-21 12:00 UTC


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    """Metric output captured in a buffer, and switched off again afterwards."""
    buffer = io.StringIO()
    metrics.enable_emf_output(buffer)
    yield buffer
    metrics.disable_emf_output()


def test_a_data_point_is_a_valid_embedded_metric() -> None:
    line = metrics.spend_fraction_line(0.82, now=NOON)

    record: dict[str, Any] = json.loads(line)
    assert record["DailySpendFraction"] == 0.82
    directive = record["_aws"]["CloudWatchMetrics"][0]
    assert record["_aws"]["Timestamp"] == int(NOON * 1000)
    assert directive["Namespace"] == "CommitmentTracker"
    assert directive["Dimensions"] == [[]]
    assert directive["Metrics"] == [{"Name": "DailySpendFraction", "Unit": "None"}]
    assert "\n" not in line


def test_the_line_is_written_bare_so_cloudwatch_can_parse_it(stream: io.StringIO) -> None:
    metrics.emit_spend_fraction(0.5)

    (line,) = stream.getvalue().splitlines()
    assert json.loads(line)["DailySpendFraction"] == 0.5


def test_nothing_is_written_until_output_is_enabled(capsys: pytest.CaptureFixture[str]) -> None:
    assert not metrics.emf_output_enabled()

    metrics.emit_spend_fraction(0.5)

    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")


def test_output_can_be_switched_off_again(stream: io.StringIO) -> None:
    assert metrics.emf_output_enabled()
    metrics.disable_emf_output()
    assert not metrics.emf_output_enabled()
    metrics.emit_spend_fraction(0.5)
    assert stream.getvalue() == ""


def test_enabling_twice_writes_each_line_once(stream: io.StringIO) -> None:
    metrics.enable_emf_output(stream)
    metrics.emit_spend_fraction(0.1)
    assert len(stream.getvalue().splitlines()) == 1


def test_metric_lines_do_not_propagate_to_the_application_log() -> None:
    # (pytest attaches its own capture handlers to such loggers, so caplog can't show this.)
    assert logging.getLogger("commitment_tracker.metrics").propagate is False


@pytest.mark.parametrize("fraction", [-0.1, float("nan"), float("inf")])
def test_a_fraction_that_is_not_a_fraction_is_rejected(fraction: float) -> None:
    with pytest.raises(ValueError, match="fraction"):
        metrics.spend_fraction_line(fraction, now=NOON)


# --- The spend cap reports its fraction ----------------------------------------------------------


def test_the_cap_reports_the_day_s_fraction_after_each_record() -> None:
    seen: list[float] = []
    cap = SpendCap(MemorySpendStore(), 4.0, clock=lambda: NOON, on_total=seen.append)

    cap.record(1.0)
    cap.record(1.0)

    assert seen == [0.25, 0.5]


def test_a_failing_report_does_not_break_recording(caplog: pytest.LogCaptureFixture) -> None:
    def boom(fraction: float) -> None:
        raise RuntimeError("no output")

    store = MemorySpendStore()
    cap = SpendCap(store, 4.0, clock=lambda: NOON, on_total=boom)

    with caplog.at_level(logging.WARNING):
        cap.record(1.0)

    assert store.total_micros("2025-10-21") == 1_000_000
    assert "spend report failed" in caplog.text


def test_the_deployed_cap_emits_the_metric(
    stream: io.StringIO, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(
        "commitment_tracker.api.app.DynamoSpendStore", lambda client, table: MemorySpendStore()
    )
    cap = build_spend_cap(Settings(_env_file=None, guardrails_table="g", daily_budget_usd=2.0))
    assert cap is not None

    cap.record(1.0)

    (line,) = stream.getvalue().splitlines()
    assert json.loads(line)["DailySpendFraction"] == 0.5
