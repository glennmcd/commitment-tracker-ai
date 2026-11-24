"""`uv run eval --estimate`: price a run from the response cache, without building the model."""

import re
from pathlib import Path

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.extractor.adapter import ModelReply, ModelRequest
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.schemas import Label
from commitment_tracker.settings import Settings
from tests.eval.test_cli import run_cli
from tests.fakes import FunctionAdapter
from tests.test_two_stage import labeller

ESTIMATE_TOTAL = re.compile(r"^total: .*est\. (?P<usd>\$[0-9.]+|n/a)$", re.MULTILINE)
PROMISE_DATA = (
    '{"id": "p", "call_date": "2026-10-21", "turns": [{"speaker": "seller", "text": '
    '"We promise to send it."}, {"speaker": "buyer", "text": "Thanks."}], "expected": '
    '[{"turn_index": 0, "label": "NONE", "quote": "We promise to send it."}], '
    '"provenance": "hand-written", "review": "accepted"}\n'
)


def refuse_to_build(settings: Settings, *, model: str | None = None) -> Extractor:
    raise AssertionError("--estimate must not build the model adapter")


def total_usd(out: str) -> float | None:
    match = ESTIMATE_TOTAL.search(out)
    assert match is not None, out
    return None if match["usd"] == "n/a" else float(match["usd"].removeprefix("$"))


def report_count(tmp_path: Path) -> int:
    return (
        len(list((tmp_path / "reports").rglob("*.json"))) if (tmp_path / "reports").exists() else 0
    )


def test_a_fully_cached_set_has_no_misses_and_no_cost(
    tmp_path: Path,
    fake_model: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli(tmp_path) == 0  # fills the cache for the default model
    reports_before = report_count(tmp_path)
    monkeypatch.setattr(cli, "build_extractor", refuse_to_build)
    assert run_cli(tmp_path, "--estimate") == 0
    out = capsys.readouterr().out
    assert "0 misses" in out
    assert "$0.0000" in out
    assert report_count(tmp_path) == reports_before


def test_a_model_with_no_cached_responses_misses_every_item(
    tmp_path: Path,
    fake_model: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli(tmp_path) == 0  # the default model's responses price the others
    calls: list[ModelRequest] = []

    def counting(settings: Settings, *, model: str | None = None) -> Extractor:
        def answer(request: ModelRequest) -> ModelReply | Exception:
            calls.append(request)
            raise AssertionError("--estimate must not call the model")

        return Extractor(FunctionAdapter(answer, model=model or "x"), load_prompt("v1"))

    monkeypatch.setattr(cli, "build_extractor", counting)
    assert run_cli(tmp_path, "--estimate", "--model", "claude-sonnet-5-5") == 0
    out = capsys.readouterr().out
    assert "1 of 1 calls miss the cache" in out
    usd = total_usd(out)
    assert usd is not None and usd > 0
    assert "no cached claude-sonnet-5-5 responses" in out
    assert calls == []


def test_an_unpriced_model_gets_a_miss_count_but_no_cost(
    tmp_path: Path,
    fake_model: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli(tmp_path) == 0
    monkeypatch.setattr(cli, "build_extractor", refuse_to_build)
    assert run_cli(tmp_path, "--estimate", "--model", "claude-unpriced-1") == 0
    out = capsys.readouterr().out
    assert "1 of 1 calls miss the cache" in out
    assert total_usd(out) is None


def test_no_cache_counts_every_item_as_a_miss(
    tmp_path: Path,
    fake_model: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli(tmp_path) == 0
    monkeypatch.setattr(cli, "build_extractor", refuse_to_build)
    assert run_cli(tmp_path, "--estimate", "--no-cache") == 0
    assert "1 of 1 calls miss the cache" in capsys.readouterr().out


def test_two_stage_prices_extract_windows_the_screen_has_already_flagged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rules = {"promise": Label.COMMITMENT}

    def build(settings: Settings, *, model: str | None = None) -> Extractor:
        chosen = model or settings.extractor_model
        return Extractor(FunctionAdapter(labeller(rules), model=chosen), load_prompt("v1"))

    monkeypatch.setattr(cli, "build_extractor", build)
    data = tmp_path / "promise.jsonl"
    data.write_text(PROMISE_DATA, encoding="utf-8")
    base = [
        "--data",
        str(data),
        "--reports-dir",
        str(tmp_path / "r"),
        "--cache-dir",
        str(tmp_path / "c"),
    ]

    # A plain Haiku run fills the screen's cache; the extract model has no responses yet.
    assert cli.main([*base, "--model", "claude-haiku-5-5"]) == 0
    assert cli.main([*base, "--estimate", "--config", "two-stage"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"screen .*claude-haiku-5-5: 1 call, 0 misses", out), out
    assert re.search(r"extract .*claude-opus-5-5: 1 call, 1 miss", out), out
    usd = total_usd(out)
    assert usd is not None and usd > 0


def test_a_cache_with_a_corrupt_file_still_estimates(
    tmp_path: Path,
    fake_model: list[tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli(tmp_path) == 0
    (tmp_path / "cache" / "junk.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(cli, "build_extractor", refuse_to_build)
    assert run_cli(tmp_path, "--estimate") == 0
    assert "0 misses" in capsys.readouterr().out


def test_estimate_still_needs_the_data_to_load(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "bad.jsonl"
    data.write_text("{nope\n", encoding="utf-8")
    assert cli.main(["--data", str(data), "--estimate"]) == 2
    assert "line 1" in capsys.readouterr().err
