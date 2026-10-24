"""`uv run eval`: argument handling and an end-to-end run with a fake model."""

import json
from pathlib import Path

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.extractor.errors import ModelUnavailable
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.settings import Settings
from tests.fakes import FunctionAdapter

DATA = (
    '{"id": "a", "call_date": "2026-10-21", "turns": [{"speaker": "seller", "text": "Our SLA is '
    'four hours."}], "expected": [{"turn_index": 0, "label": "NONE", "quote": "Our SLA is four '
    'hours."}], "provenance": "hand-written", "review": "accepted"}\n'
)


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
    reports = sorted(p.suffix for p in (tmp_path / "reports" / "adhoc").iterdir())
    assert reports == [".json", ".md"]
    (json_report,) = (tmp_path / "reports" / "adhoc").glob("*.json")
    assert json.loads(json_report.read_text(encoding="utf-8"))["run"]["model"] == "claude-haiku-5-5"
    assert "ledger F1" in capsys.readouterr().out


def test_second_run_uses_the_cache(tmp_path: Path, fake_model: list[tuple[str, str]]) -> None:
    run_cli(tmp_path)
    run_cli(tmp_path)
    reports = sorted((tmp_path / "reports" / "adhoc").glob("*.json"))
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
    assert len(list((tmp_path / "reports" / "adhoc").glob("*.md"))) == 1
    out = capsys.readouterr()
    assert "1 of 1 items failed" in out.err


# --- named sets ----------------------------------------------------------------------------------


def make_set(root: Path, name: str, role: str = "test") -> None:
    directory = root / name
    directory.mkdir(parents=True)
    manifest = {"name": name, "role": role, "gated": role == "test", "sources": []}
    (directory / "set.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "items.jsonl").write_text(DATA, encoding="utf-8")


def run_set(tmp_path: Path, *extra: str) -> int:
    return cli.main(
        [
            "--sets-dir",
            str(tmp_path / "sets"),
            "--reports-dir",
            str(tmp_path / "reports"),
            "--cache-dir",
            str(tmp_path / "cache"),
            *extra,
        ]
    )


def test_a_set_run_pins_the_set_and_writes_under_its_name(
    tmp_path: Path, fake_model: list[tuple[str, str]]
) -> None:
    make_set(tmp_path / "sets", "test")
    assert run_set(tmp_path, "--set", "test") == 0
    (report,) = (tmp_path / "reports" / "test").glob("*.json")
    run = json.loads(report.read_text(encoding="utf-8"))["run"]
    assert run["set_name"] == "test"
    assert len(run["set_sha256"]) == 64
    assert run["set_items"] == 1


def test_dev_is_the_default_set(tmp_path: Path, fake_model: list[tuple[str, str]]) -> None:
    make_set(tmp_path / "sets", "dev", role="dev")
    assert run_set(tmp_path) == 0
    assert len(list((tmp_path / "reports" / "dev").glob("*.json"))) == 1


def test_staging_runs_are_written_to_adhoc(
    tmp_path: Path, fake_model: list[tuple[str, str]]
) -> None:
    make_set(tmp_path / "sets", "staging/gem01", role="staging")
    assert run_set(tmp_path, "--set", "staging/gem01") == 0
    assert len(list((tmp_path / "reports" / "adhoc").glob("*.json"))) == 1


def test_test_runs_say_which_prompts_already_looked(
    tmp_path: Path, fake_model: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    make_set(tmp_path / "sets", "test")
    run_set(tmp_path, "--set", "test")
    assert "already: none" in capsys.readouterr().out
    run_set(tmp_path, "--set", "test")
    assert "already: v1" in capsys.readouterr().out


def test_set_and_data_are_exclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--set", "dev", "--data", "x.jsonl"])


def test_unknown_set_exits_2(
    tmp_path: Path, fake_model: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_set(tmp_path, "--set", "nope") == 2
    assert "no set named 'nope'" in capsys.readouterr().err
