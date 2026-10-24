"""The regression gate: committed reports against eval/baseline.json, with no model calls."""

import json
import re
from pathlib import Path

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.gate import (
    BASELINE_PATH,
    GATED_CONFIGURATIONS,
    Baseline,
    Current,
    GateError,
    check,
    load_baseline,
    updated_baseline,
    write_baseline,
)
from commitment_tracker.evaluation.report import build_report, write_report
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.evaluation.sets import load_set
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.settings import CONFIGURATIONS, Settings, configuration_for_model
from tests.eval.builders import exp, item, pred, response
from tests.eval.test_report import RUN
from tests.eval.test_set_loading import write_set

STACK = Path(__file__).resolve().parents[3] / "infra" / "lib" / "api-stack.ts"
PROMPT = load_prompt("v1")
CURRENT = Current(prompt_version="v1", prompt_sha256=PROMPT.sha256, effort="medium")

ITEMS = [
    item(
        f"c-{n}",
        [f"I'll send part {n} Friday."],
        [exp(0, "COMMITMENT", f"I'll send part {n} Friday.")],
    )
    for n in range(4)
]


def results(wrong: int = 0, failed: int = 0) -> list[ItemResult]:
    out = []
    for index, it in enumerate(ITEMS):
        text = it.turns[0].text
        if index < failed:
            out.append(ItemResult(it, None, "model_unavailable", False))
        elif index < failed + wrong:
            out.append(ItemResult(it, response(pred(0, "NONE", text)), None, False))
        else:
            out.append(
                ItemResult(it, response(pred(0, "COMMITMENT", text), cost_usd=0.01), None, False)
            )
    return out


class Repo:
    """A throwaway backend: a gated test set, its reports and a baseline."""

    def __init__(self, tmp_path: Path) -> None:
        self.sets = tmp_path / "sets"
        self.reports = tmp_path / "reports"
        write_set(self.sets, "test", [i.model_dump(mode="json") for i in ITEMS])
        self.sha = load_set("test", self.sets).sha256

    def report(self, configuration: str = "opus", minute: int = 0, **kwargs: int) -> Path:
        run = RUN.model_copy(
            update={
                "model": CONFIGURATIONS[configuration][0],
                "configuration": configuration,
                "stages": {"extract": CONFIGURATIONS[configuration][0]},
                "prompt_sha256": PROMPT.sha256,
                "set_name": "test",
                "set_sha256": self.sha,
                "started_at": RUN.started_at.replace(minute=minute),
            }
        )
        json_path, _ = write_report(build_report(run, results(**kwargs)), self.reports / "test")
        return json_path

    def baseline(
        self, configurations: tuple[str, ...] = ("opus",), existing: Baseline | None = None
    ) -> Baseline:
        return updated_baseline(CURRENT, configurations, self.sets, self.reports, existing)

    def check(self, baseline: Baseline, current: Current = CURRENT) -> list[str]:
        return check(baseline, current, self.sets, self.reports).failures


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path)


def test_a_matching_report_passes(repo: Repo) -> None:
    repo.report()
    result = check(repo.baseline(), CURRENT, repo.sets, repo.reports)
    assert result.ok
    assert result.passes == ["test/opus: ledger F1 1.000 (baseline 1.000, +0.000)"]


def test_a_missing_report_fails_with_the_command_to_run(repo: Repo) -> None:
    repo.report()
    baseline = repo.baseline()
    for path in (repo.reports / "test").glob("*"):
        path.unlink()
    (failure,) = repo.check(baseline)
    assert "uv run eval --set test --config opus --prompt v1 --effort medium" in failure


def test_a_prompt_change_needs_a_new_report(repo: Repo) -> None:
    repo.report()
    changed = Current(prompt_version="v2", prompt_sha256="0" * 64, effort="medium")
    (failure,) = repo.check(repo.baseline(), changed)
    assert "no report for prompt v2" in failure


def test_a_changed_set_needs_a_new_baseline(repo: Repo) -> None:
    repo.report()
    baseline = repo.baseline()
    baseline.sets["test"].set_sha256 = "0" * 64
    (failure,) = repo.check(baseline)
    assert "the set changed" in failure


def test_a_drop_of_more_than_two_points_fails(repo: Repo) -> None:
    repo.report(wrong=1)
    baseline = repo.baseline()
    current_f1 = baseline.sets["test"].configurations["opus"].ledger_f1
    baseline.sets["test"].configurations["opus"].ledger_f1 = current_f1 + 0.0201
    (failure,) = repo.check(baseline)
    assert "dropped more than 0.02" in failure


def test_a_drop_of_exactly_two_points_passes(repo: Repo) -> None:
    repo.report(wrong=1)
    baseline = repo.baseline()
    current_f1 = baseline.sets["test"].configurations["opus"].ledger_f1
    baseline.sets["test"].configurations["opus"].ledger_f1 = current_f1 + 0.02
    assert repo.check(baseline) == []


def test_failed_items_fail(repo: Repo) -> None:
    repo.report(failed=1)
    baseline = repo.baseline()
    failures = repo.check(baseline)
    assert any("1 items failed" in f for f in failures)


def test_stale_scores_fail(repo: Repo) -> None:
    path = repo.report()
    baseline = repo.baseline()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scores"]["accuracy"] = 0.5
    path.write_text(json.dumps(data), encoding="utf-8")
    (failure,) = repo.check(baseline)
    assert "stale scores" in failure and "uv run eval rescore --set test" in failure


def test_field_accuracy_changes_only_warn(repo: Repo) -> None:
    repo.report()
    baseline = repo.baseline()
    baseline.sets["test"].configurations["opus"].field_accuracy["owner"] = 0.5
    result = check(baseline, CURRENT, repo.sets, repo.reports)
    assert result.ok
    assert any("owner accuracy" in w for w in result.warnings)


def test_the_latest_matching_report_is_used(repo: Repo) -> None:
    repo.report(minute=0, wrong=2)
    baseline = repo.baseline()  # baselines the worse run
    repo.report(minute=5)
    result = check(baseline, CURRENT, repo.sets, repo.reports)
    assert result.ok and "+" in result.passes[0]


def test_a_gated_set_with_items_but_no_baseline_fails(repo: Repo) -> None:
    (failure,) = repo.check(Baseline())
    assert "no baseline" in failure


def test_an_empty_gated_set_passes(tmp_path: Path) -> None:
    write_set(tmp_path / "sets", "test", [])
    result = check(Baseline(), CURRENT, tmp_path / "sets", tmp_path / "reports")
    assert result.ok and result.passes == ["test: no items yet"]


def test_update_baseline_needs_every_configuration(repo: Repo) -> None:
    repo.report("opus")
    with pytest.raises(GateError, match="test/haiku: no report"):
        repo.baseline(("opus", "haiku"))
    repo.report("haiku", minute=1)
    baseline = repo.baseline(("opus", "haiku"))
    assert set(baseline.sets["test"].configurations) == {"opus", "haiku"}
    assert baseline.sets["test"].configurations["haiku"].model == "claude-haiku-5-5"


def test_cli_gate_and_update(
    repo: Repo, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.report("opus")
    repo.report("haiku", minute=1)
    baseline_path = tmp_path / "baseline.json"
    common = [
        "--sets-dir",
        str(repo.sets),
        "--reports-dir",
        str(repo.reports),
        "--baseline",
        str(baseline_path),
    ]
    assert cli.gate_main(common) == 1  # no baseline yet for a set with items
    assert cli.gate_main([*common, "--update-baseline"]) == 0
    assert load_baseline(baseline_path).sets["test"].set_sha256 == repo.sha
    assert cli.gate_main(common) == 0
    out = capsys.readouterr().out
    assert "PASS test/opus" in out and "PASS test/haiku" in out


def test_updating_one_configuration_keeps_the_others(repo: Repo) -> None:
    repo.report("opus")
    repo.report("haiku", minute=1)
    both = repo.baseline(("opus", "haiku"))
    repo.report("opus", minute=2, wrong=1)
    updated = repo.baseline(("opus",), existing=both)
    entries = updated.sets["test"].configurations
    assert set(entries) == {"opus", "haiku"}
    assert entries["opus"].ledger_f1 < both.sets["test"].configurations["opus"].ledger_f1
    assert entries["haiku"] == both.sets["test"].configurations["haiku"]


def test_a_changed_set_needs_every_baselined_configuration_again(repo: Repo) -> None:
    repo.report("opus")
    repo.report("haiku", minute=1)
    stale = repo.baseline(("opus", "haiku"))
    stale.sets["test"].set_sha256 = "0" * 64
    for path in (repo.reports / "test").glob("*haiku*"):
        path.unlink()  # haiku must be re-run on the new set before the baseline can move
    with pytest.raises(GateError, match="test/haiku: no report"):
        repo.baseline(("opus",), existing=stale)


def test_a_model_swap_behind_a_configuration_needs_a_new_report(
    repo: Repo, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.report("opus")
    baseline = repo.baseline()
    monkeypatch.setitem(CONFIGURATIONS, "opus", ("claude-opus-6-0",))
    (failure,) = repo.check(baseline)
    assert "no report" in failure and "claude-opus-6-0" in failure


# --- the committed files -------------------------------------------------------------------------


def test_the_committed_reports_pass_the_gate() -> None:
    result = check(load_baseline(), cli.gate_current())
    assert result.ok, result.failures


def test_the_gate_covers_the_deployed_demo_model() -> None:
    match = re.search(r'DEFAULT_DEMO_MODEL = "([^"]+)"', STACK.read_text(encoding="utf-8"))
    assert match, "DEFAULT_DEMO_MODEL not found in api-stack.ts"
    demo = configuration_for_model(match.group(1))
    assert demo in GATED_CONFIGURATIONS
    for name, gated in load_baseline().sets.items():
        assert demo in gated.configurations, f"{name} baseline lacks the demo model"


def test_the_gate_covers_the_default_model() -> None:
    default = Settings.model_fields["extractor_model"].default
    assert configuration_for_model(default) in GATED_CONFIGURATIONS


def test_the_committed_baseline_is_written_as_the_tool_writes_it(tmp_path: Path) -> None:
    roundtrip = tmp_path / "baseline.json"
    write_baseline(load_baseline(), roundtrip)
    assert roundtrip.read_bytes() == BASELINE_PATH.read_bytes()
