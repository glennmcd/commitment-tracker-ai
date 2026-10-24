"""`uv run eval --offline`: answer only from the response cache, never build the real adapter."""

import asyncio
import json
from pathlib import Path

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.cache import CacheMiss, OfflineAdapter
from commitment_tracker.extractor.adapter import ModelRequest
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.model_output import ModelOutput
from commitment_tracker.settings import Settings
from tests.eval.test_cli import run_cli


def refuse_to_build(settings: Settings, *, model: str | None = None) -> Extractor:
    raise AssertionError("--offline must not build the real extractor")


def test_offline_runs_from_a_warm_cache(
    tmp_path: Path, fake_model: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run_cli(tmp_path) == 0  # fills the cache with the fake model
    monkeypatch.setattr(cli, "build_extractor", refuse_to_build)
    assert run_cli(tmp_path, "--offline") == 0
    latest = sorted((tmp_path / "reports" / "adhoc").glob("*.json"))[-1]
    assert json.loads(latest.read_text(encoding="utf-8"))["scores"]["cache_hits"] == 1


def test_offline_with_a_cold_cache_exits_before_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "build_extractor", refuse_to_build)
    assert run_cli(tmp_path, "--offline") == 1
    assert "1 of 1 items are not cached (first: a)" in capsys.readouterr().err
    assert not (tmp_path / "reports").exists()


def test_offline_and_no_cache_conflict(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run_cli(tmp_path, "--offline", "--no-cache")


def test_the_offline_adapter_raises_cache_miss_on_any_call() -> None:
    adapter = OfflineAdapter("claude-opus-5-5")
    request = ModelRequest(system="s", messages=(), output_model=ModelOutput)
    with pytest.raises(CacheMiss):
        asyncio.run(adapter.complete(request))
