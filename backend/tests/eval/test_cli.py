"""`uv run eval`: argument handling and an end-to-end run with a fake model."""

import json
from pathlib import Path

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.extractor.errors import ModelUnavailable
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.settings import Settings
from tests.eval.test_runner import all_none
from tests.fakes import FunctionAdapter

DATA = (
    '{"id": "a", "call_date": "2026-10-21", "turns": [{"speaker": "seller", "text": "Our SLA is '
    'four hours."}], "expected": [{"turn_index": 0, "label": "NONE", "quote": "Our SLA is four '
    'hours."}], "provenance": "hand-written", "review": "accepted"}\n'
)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Replaces the Anthropic extractor; records (model, prompt version) for each build."""
    built: list[tuple[str, str]] = []

    def build(settings: Settings, *, model: str | None = None) -> Extractor:
        chosen = model or settings.extractor_model
        built.append((chosen, settings.prompt_version))
        return Extractor(
            FunctionAdapter(all_none, model=chosen), load_prompt(settings.prompt_version)
        )

    monkeypatch.setattr(cli, "build_extractor", build)
    return built


def run_cli(tmp_path: Path, *extra: str) -> int:
    data = tmp_path / "set.jsonl"
    data.write_text(DATA, encoding="utf-8")
    return cli.main(
        [
            "--data",
            str(data),
            "--reports-dir",
            str(tmp_path / "reports"),
            "--cache-dir",
            str(tmp_path / "cache"),
            *extra,
        ]
    )


def test_runs_and_writes_both_reports(
    tmp_path: Path, fake_model: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(tmp_path, "--model", "claude-haiku-5-5", "--prompt", "v1") == 0
    assert fake_model == [("claude-haiku-5-5", "v1")]
    reports = sorted(p.suffix for p in (tmp_path / "reports").iterdir())
    assert reports == [".json", ".md"]
    (json_report,) = (tmp_path / "reports").glob("*.json")
    assert json.loads(json_report.read_text(encoding="utf-8"))["run"]["model"] == "claude-haiku-5-5"
    assert "ledger F1" in capsys.readouterr().out


def test_second_run_uses_the_cache(tmp_path: Path, fake_model: list[tuple[str, str]]) -> None:
    run_cli(tmp_path)
    run_cli(tmp_path)
    reports = sorted((tmp_path / "reports").glob("*.json"))
    latest = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert latest["scores"]["cache_hits"] == 1


def test_no_cache_flag(tmp_path: Path, fake_model: list[tuple[str, str]]) -> None:
    run_cli(tmp_path, "--no-cache")
    assert not (tmp_path / "cache").exists()


def test_unknown_prompt_version_exits_2(
    tmp_path: Path, fake_model: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_cli(tmp_path, "--prompt", "v999") == 2
    assert "v999" in capsys.readouterr().err


def test_bad_dataset_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = tmp_path / "bad.jsonl"
    data.write_text("{nope\n", encoding="utf-8")
    assert cli.main(["--data", str(data), "--reports-dir", str(tmp_path)]) == 2
    assert "line 1" in capsys.readouterr().err


def test_failed_items_still_write_a_report_but_exit_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def build(settings: Settings, *, model: str | None = None) -> Extractor:
        failing = FunctionAdapter(lambda _: ModelUnavailable("no Anthropic credentials"))
        return Extractor(failing, load_prompt("v1"))

    monkeypatch.setattr(cli, "build_extractor", build)
    assert run_cli(tmp_path) == 1
    assert len(list((tmp_path / "reports").glob("*.md"))) == 1
    out = capsys.readouterr()
    assert "1 of 1 items failed" in out.err
