"""`uv run eval-export-site`: the static data behind the /evals pages, deterministic, complete."""

import json
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.report import build_report, write_report
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.evaluation.sets import load_set
from commitment_tracker.evaluation.site_export import SITE_DATA_DIR, export_site
from tests.eval.builders import exp, item, pred, response
from tests.eval.test_report import RUN
from tests.eval.test_set_loading import write_set

ITEMS = [
    item("c-1", ["I'll send it Friday."], [exp(0, "COMMITMENT", "I'll send it Friday.")]),
    item("n-1", ["Our SLA is four hours."], [exp(0, "NONE", "Our SLA is four hours.")]),
]


def results(right: bool = True) -> list[ItemResult]:
    label = "COMMITMENT" if right else "NONE"
    return [
        ItemResult(ITEMS[0], response(pred(0, label, "I'll send it Friday.")), None, False),
        ItemResult(ITEMS[1], response(pred(0, "NONE", "Our SLA is four hours.")), None, True),
    ]


class Repo:
    def __init__(self, tmp_path: Path) -> None:
        self.sets = tmp_path / "sets"
        self.reports = tmp_path / "reports"
        self.out = tmp_path / "out"
        write_set(self.sets, "test", [i.model_dump(mode="json") for i in ITEMS])
        write_set(self.sets, "dev", [], role="dev", gated=False)
        self.sha = load_set("test", self.sets).sha256

    def report(self, configuration: str, minute: int, folder: str = "test", **kw: Any) -> str:
        run = RUN.model_copy(
            update={
                "model": f"model-{configuration}",
                "configuration": configuration,
                "set_name": "test" if folder != "adhoc" else None,
                "set_sha256": self.sha if folder != "adhoc" else None,
                "started_at": RUN.started_at.replace(minute=minute),
            }
        )
        path, _ = write_report(build_report(run, results(**kw)), self.reports / folder)
        return path.stem

    def export(self) -> dict[str, Any]:
        export_site(self.sets, self.reports, self.out)
        index: dict[str, Any] = json.loads((self.out / "index.json").read_text(encoding="utf-8"))
        return index


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def test_the_index_lists_sets_runs_and_the_latest_run_per_configuration(repo: Repo) -> None:
    old = repo.report("opus", 0, right=False)
    new = repo.report("opus", 5)
    haiku = repo.report("haiku", 1)
    index = repo.export()
    assert [s["name"] for s in index["sets"]] == ["dev", "test"]
    rows = {row["configuration"]: row for row in index["results"]["test"]}
    assert rows["opus"]["run"] == new
    assert rows["haiku"]["run"] == haiku
    assert rows["opus"]["ledger_f1"] == 1.0
    assert {r["run"] for r in index["runs"]} == {old, new, haiku}


def test_adhoc_runs_are_never_published(repo: Repo) -> None:
    repo.report("opus", 0, folder="adhoc")
    index = repo.export()
    assert index["runs"] == []
    assert not list((repo.out / "runs").glob("*.json"))


def test_a_run_file_joins_items_with_transcripts_and_judgement(repo: Repo) -> None:
    stem = repo.report("opus", 0, right=False)
    repo.export()
    run = json.loads((repo.out / "runs" / f"{stem}.json").read_text(encoding="utf-8"))
    first, second = run["items"]
    assert first["turns"] == [{"speaker": "seller", "text": "I'll send it Friday."}]
    assert first["expected"][0]["label"] == "COMMITMENT"
    assert first["predicted"][0]["label"] == "NONE"
    assert (first["correct"], second["correct"]) == (False, True)
    assert run["scores"]["ledger"]["f1"] == 0.0
    assert run["run"]["configuration"] == run["configuration"] == "opus"


def test_the_export_is_deterministic(repo: Repo) -> None:
    repo.report("opus", 0)
    repo.export()
    first = {p.name: p.read_bytes() for p in repo.out.rglob("*.json")}
    repo.export()
    assert {p.name: p.read_bytes() for p in repo.out.rglob("*.json")} == first
    text = (repo.out / "index.json").read_text(encoding="utf-8")
    assert "\r" not in text


def test_stale_run_files_are_removed(repo: Repo) -> None:
    repo.report("opus", 0)
    (repo.out / "runs").mkdir(parents=True)
    (repo.out / "runs" / "gone.json").write_text("{}", encoding="utf-8")
    repo.export()
    assert not (repo.out / "runs" / "gone.json").exists()


def test_legacy_reports_are_published_and_flagged(repo: Repo, tmp_path: Path) -> None:
    legacy = repo.reports / "dev" / "20261022T040145Z-claude-haiku-5-5-v1.json"
    legacy.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "eval" / "reports" / "dev" / legacy.name
    legacy.write_bytes(source.read_bytes())
    index = repo.export()
    (row,) = index["runs"]
    assert (row["legacy"], row["set"], row["configuration"]) == (True, "dev", "haiku")
    run = json.loads((repo.out / "runs" / f"{legacy.stem}.json").read_text(encoding="utf-8"))
    assert run["items"][0]["predicted"] is None
    assert run["items"][0]["correct"] is None


def test_cli_writes_to_the_given_directory(repo: Repo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.report("opus", 0)
    argv = [
        "--sets-dir",
        str(repo.sets),
        "--reports-dir",
        str(repo.reports),
        "--out",
        str(repo.out),
    ]
    assert cli.export_site_main(argv) == 0
    assert (repo.out / "index.json").is_file()
    assert "1 runs" in capsys.readouterr().out


def test_the_committed_export_is_current(tmp_path: Path) -> None:
    export_site(out=tmp_path)
    for path in sorted(tmp_path.rglob("*.json")):
        committed = SITE_DATA_DIR / path.relative_to(tmp_path)
        assert committed.is_file(), f"{committed} is missing; run uv run eval-export-site"
        assert committed.read_bytes() == path.read_bytes(), (
            f"{committed} is stale; run uv run eval-export-site"
        )
    produced = {p.relative_to(tmp_path) for p in tmp_path.rglob("*.json")}
    committed_files = {p.relative_to(SITE_DATA_DIR) for p in SITE_DATA_DIR.rglob("*.json")}
    assert committed_files == produced, "stale files in the export; run uv run eval-export-site"
