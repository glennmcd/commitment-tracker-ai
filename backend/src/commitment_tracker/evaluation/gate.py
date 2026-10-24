"""`uv run eval-gate`: the regression gate (ADR 0012), a pure check over committed files.

CI never calls a model. For every gated set and every configuration in eval/baseline.json, the gate
takes the current configuration (prompt version and effort from the `Settings` field defaults, not
the environment, and the prompt file's hash), finds the latest committed report for that
configuration, prompt and set version, and fails when:

- no such report exists (it prints the command that writes one);
- the set's hash differs from the baseline's: the set changed, so re-baseline on purpose;
- ledger F1 dropped by more than 0.02 from the baseline (both rounded to six places first, so a
  drop of exactly 0.02 passes), or any item failed;
- the report's stored scores differ from a re-score of its stored predictions with today's
  metrics code (run `uv run eval rescore`).

Field-accuracy changes are printed as warnings. `--update-baseline` writes the baseline from the
latest matching reports, for when a change in score is intended.
"""

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.report import DEFAULT_REPORTS_DIR, Report, RunInfo
from commitment_tracker.evaluation.rescore import RescoreError, rescore
from commitment_tracker.evaluation.sets import SETS_DIR, list_sets, load_manifest, load_set
from commitment_tracker.settings import CONFIGURATIONS

# backend/src/commitment_tracker/evaluation/gate.py -> backend/eval/baseline.json
BACKEND_DIR = Path(__file__).resolve().parents[3]
BASELINE_PATH = BACKEND_DIR / "eval" / "baseline.json"
MAX_LEDGER_F1_DROP = 0.02
# The default model's configuration and the deployed demo's (DEFAULT_DEMO_MODEL in
# infra/lib/api-stack.ts); a test keeps the second in step with the stack.
GATED_CONFIGURATIONS = ("opus", "haiku")


class GateError(ValueError):
    pass


class BaselineEntry(BaseModel):
    model: str
    effort: str
    prompt_version: str
    prompt_sha256: str
    report: str  # path relative to backend/
    ledger_f1: float
    field_accuracy: dict[str, float | None]
    failed_items: int


class BaselineSet(BaseModel):
    set_sha256: str
    configurations: dict[str, BaselineEntry] = Field(default_factory=dict)


class Baseline(BaseModel):
    sets: dict[str, BaselineSet] = Field(default_factory=dict)


@dataclass(frozen=True)
class Current:
    """What the gate holds reports to: the committed defaults, not the environment."""

    prompt_version: str
    prompt_sha256: str
    effort: str


@dataclass
class GateResult:
    passes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures


def load_baseline(path: Path = BASELINE_PATH) -> Baseline:
    if not path.is_file():
        return Baseline()
    return Baseline.model_validate_json(path.read_text(encoding="utf-8"))


def stage_models(run: RunInfo) -> tuple[str, ...]:
    """The models a run used, ordered as in CONFIGURATIONS: (screen, extract) or (model,)."""
    return tuple(run.stages[stage] for stage in ("screen", "extract") if stage in run.stages)


def latest_report(
    reports_dir: Path, set_name: str, set_sha256: str, configuration: str, current: Current
) -> tuple[Path, Report] | None:
    """The newest report of this configuration, on this set version, with the current prompt and
    effort, and run by the models the configuration names today: a model swap needs a new run."""
    expected_models = CONFIGURATIONS.get(configuration)
    matches = []
    for path in (reports_dir / set_name).glob("*.json"):
        report = Report.model_validate_json(path.read_text(encoding="utf-8"))
        run = report.run
        if (
            run.configuration == configuration
            and run.set_sha256 == set_sha256
            and run.prompt_sha256 == current.prompt_sha256
            and run.effort == current.effort
            and (expected_models is None or stage_models(run) == expected_models)
        ):
            matches.append((run.started_at, path, report))
    if not matches:
        return None
    _, path, report = max(matches, key=lambda match: match[0])
    return path, report


def _run_command(set_name: str, configuration: str, current: Current) -> str:
    return (
        f"uv run eval --set {set_name} --config {configuration} "
        f"--prompt {current.prompt_version} --effort {current.effort}"
    )


def _check_entry(
    result: GateResult,
    label: str,
    entry: BaselineEntry,
    found: tuple[Path, Report],
    items: dict[str, EvalItem],
) -> None:
    path, report = found
    try:
        rescored = rescore(report, items)
    except RescoreError as error:
        result.failures.append(f"{label}: {path.name} can't be re-scored ({error}); run it again")
        return
    if rescored.scores != report.scores or rescored.two_stage != report.two_stage:
        result.failures.append(
            f"{label}: {path.name} has stale scores; run uv run eval rescore --set "
            f"{report.run.set_name}"
        )
        return
    scores = report.scores
    current_f1, baseline_f1 = round(scores.ledger.f1, 6), round(entry.ledger_f1, 6)
    drop = round(baseline_f1 - current_f1, 6)
    summary = (
        f"ledger F1 {current_f1:.3f} (baseline {baseline_f1:.3f}, {current_f1 - baseline_f1:+.3f})"
    )
    failed = len(result.failures)
    if drop > MAX_LEDGER_F1_DROP:
        result.failures.append(f"{label}: {summary} dropped more than {MAX_LEDGER_F1_DROP}")
    if scores.failed_items:
        result.failures.append(f"{label}: {len(scores.failed_items)} items failed in {path.name}")
    if len(result.failures) == failed:
        result.passes.append(f"{label}: {summary}")
    for name, field_score in scores.fields.items():
        before = entry.field_accuracy.get(name)
        if field_score.accuracy != before:
            result.warnings.append(
                f"{label}: {name} accuracy {field_score.accuracy} (baseline {before})"
            )


def check(
    baseline: Baseline,
    current: Current,
    sets_root: Path = SETS_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
) -> GateResult:
    result = GateResult()
    for name in list_sets(sets_root):
        manifest = load_manifest(name, sets_root)
        if not manifest.gated or manifest.kind != "text":
            continue
        loaded = load_set(name, sets_root, allow_empty=True)
        expected = baseline.sets.get(name)
        if expected is None:
            if loaded.items:
                result.failures.append(
                    f"{name}: no baseline; run the gated configurations, then "
                    "uv run eval-gate --update-baseline"
                )
            else:
                result.passes.append(f"{name}: no items yet")
            continue
        if expected.set_sha256 != loaded.sha256:
            result.failures.append(
                f"{name}: the set changed (sha256 {loaded.sha256[:12]}, baseline "
                f"{expected.set_sha256[:12]}); re-run and re-baseline on purpose"
            )
            continue
        items = {item.id: item for item in loaded.items}
        for configuration, entry in expected.configurations.items():
            label = f"{name}/{configuration}"
            found = latest_report(reports_dir, name, loaded.sha256, configuration, current)
            if found is None:
                models = ", ".join(CONFIGURATIONS.get(configuration, ())) or configuration
                result.failures.append(
                    f"{label}: no report for prompt {current.prompt_version} "
                    f"(sha256 {current.prompt_sha256[:12]}) and {models} on this set; run "
                    f"{_run_command(name, configuration, current)}"
                )
                continue
            _check_entry(result, label, entry, found, items)
    return result


def updated_baseline(
    current: Current,
    configurations: tuple[str, ...] = GATED_CONFIGURATIONS,
    sets_root: Path = SETS_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    existing: Baseline | None = None,
) -> Baseline:
    """The existing baseline with the given configurations refreshed from their latest matching
    reports. Other configurations keep their entries; if a set changed, every configuration already
    baselined on it must be refreshed too, so none silently drops out of the gate."""
    previous = existing or Baseline()
    baseline = Baseline(sets=dict(previous.sets))
    for name in list_sets(sets_root):
        manifest = load_manifest(name, sets_root)
        if not manifest.gated or manifest.kind != "text":
            continue
        loaded = load_set(name, sets_root, allow_empty=True)
        if not loaded.items:
            continue
        before = previous.sets.get(name)
        same_set = before is not None and before.set_sha256 == loaded.sha256
        entries = dict(before.configurations) if before is not None and same_set else {}
        refresh = list(dict.fromkeys(configurations))
        if before is not None and not same_set:
            refresh += [c for c in before.configurations if c not in refresh]
        for configuration in refresh:
            found = latest_report(reports_dir, name, loaded.sha256, configuration, current)
            if found is None:
                raise GateError(
                    f"{name}/{configuration}: no report to baseline; run "
                    f"{_run_command(name, configuration, current)}"
                )
            path, report = found
            entries[configuration] = BaselineEntry(
                model=report.run.model,
                effort=report.run.effort,
                prompt_version=report.run.prompt_version,
                prompt_sha256=report.run.prompt_sha256,
                report=path.resolve().relative_to(BACKEND_DIR).as_posix()
                if path.resolve().is_relative_to(BACKEND_DIR)
                else path.as_posix(),
                ledger_f1=report.scores.ledger.f1,
                field_accuracy={k: v.accuracy for k, v in report.scores.fields.items()},
                failed_items=len(report.scores.failed_items),
            )
        baseline.sets[name] = BaselineSet(set_sha256=loaded.sha256, configurations=entries)
    return baseline


def write_baseline(baseline: Baseline, path: Path = BASELINE_PATH) -> None:
    path.write_bytes((baseline.model_dump_json(indent=2) + "\n").encode("utf-8"))
