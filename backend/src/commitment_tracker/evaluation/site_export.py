"""`uv run eval-export-site`: the data behind the static /evals pages (ADR 0013).

Reads eval/sets/ and every report under eval/reports/ except adhoc/, and writes:

- frontend/src/data/evals/index.json: the sets, a results table per set (the latest run of each
  configuration), every run, the audio penalty and the review agreement;
- frontend/src/data/evals/runs/<run>.json: one run's scores and its items joined with their
  transcripts, expected spans, predicted spans and whether the item came out right.

The pages import these at build time; nothing is fetched at run time. Output is sorted, rounded to
six places and LF-terminated, so the same inputs always give the same bytes and CI can fail when
the committed export is stale. Run files no longer produced are removed.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from commitment_tracker.evaluation.agreement import agreement
from commitment_tracker.evaluation.compare import item_correct
from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.report import DEFAULT_REPORTS_DIR, ItemDetail, Report
from commitment_tracker.evaluation.rescore import RescoreError, result_from_detail
from commitment_tracker.evaluation.sets import (
    SETS_DIR,
    list_sets,
    load_manifest,
    load_set,
    summarize,
)
from commitment_tracker.settings import configuration_for_model

# backend/src/commitment_tracker/evaluation/site_export.py -> frontend/src/data/evals
SITE_DATA_DIR = Path(__file__).resolve().parents[4] / "frontend" / "src" / "data" / "evals"
UNPUBLISHED = {"adhoc"}
DIGITS = 6


@dataclass(frozen=True)
class ExportResult:
    runs: int
    removed: list[str]


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, DIGITS)
    if isinstance(value, dict):
        return {key: _round(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round(item) for item in value]
    return value


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_round(data), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.write_bytes(text.encode("utf-8"))


def _items_by_set(root: Path) -> dict[str, dict[str, EvalItem]]:
    """Items per published set; the audio set borrows the items of the set its clips speak."""
    by_set: dict[str, dict[str, EvalItem]] = {}
    for name in list_sets(root):
        manifest = load_manifest(name, root)
        if manifest.kind == "text":
            by_set[name] = {i.id: i for i in load_set(name, root, allow_empty=True).items}
    for name in list_sets(root):
        manifest = load_manifest(name, root)
        if manifest.kind == "audio" and manifest.items_from in by_set:
            by_set[name] = by_set[manifest.items_from]
    return by_set


def _item_entry(
    detail: ItemDetail, item: EvalItem | None, report: Report, audio: bool
) -> dict[str, Any]:
    correct: bool | None = None
    if detail.spans is not None and item is not None and not audio:
        try:
            result = result_from_detail(detail, item, report.run)
        except RescoreError:
            result = None
        if result is not None:
            spans = result.response.spans if result.response else []
            correct = result.response is not None and item_correct(item, spans)
    turns = detail.transcript if audio and detail.transcript else (item.turns if item else None)
    return {
        "id": detail.item_id,
        "tags": detail.tags,
        "provenance": detail.provenance or (item.provenance if item else None),
        "call_date": item.call_date.isoformat() if item else None,
        "note": item.note if item else None,
        "turns": [{"speaker": t.speaker, "text": t.text} for t in turns] if turns else None,
        "expected": [s.model_dump(mode="json") for s in item.expected] if item else None,
        "expected_labels": detail.expected,
        "predicted": [s.model_dump(mode="json") for s in detail.spans]
        if detail.spans is not None
        else None,
        "predicted_labels": detail.predicted,
        "correct": correct,
        "error": detail.error,
        "cached": detail.cached,
        "latency_ms": detail.latency_ms,
        "cost_usd": detail.cost_usd,
        "dropped_quotes": detail.dropped_quotes,
        "flagged_turns": detail.flagged_turns,
    }


def _configuration(report: Report) -> str:
    return report.run.configuration or configuration_for_model(report.run.model)


def _row(run_id: str, set_name: str, report: Report) -> dict[str, Any]:
    scores, run = report.scores, report.run
    return {
        "run": run_id,
        "set": set_name,
        "configuration": _configuration(report),
        "model": run.model,
        "stages": run.stages,
        "prompt_version": run.prompt_version,
        "prompt_sha256": run.prompt_sha256,
        "effort": run.effort,
        "started_at": run.started_at.isoformat(),
        "legacy": run.set_sha256 is None,
        "set_sha256": run.set_sha256,
        "items": scores.items,
        "ledger_f1": scores.ledger.f1,
        "ledger_precision": scores.ledger.precision,
        "ledger_recall": scores.ledger.recall,
        "accuracy": scores.accuracy,
        "macro_f1": scores.macro_f1,
        "fields": {name: f.accuracy for name, f in scores.fields.items()},
        "failed_items": len(scores.failed_items),
        "cost_usd": scores.cost_usd,
        "latency_p50_ms": scores.latency_ms.p50 if scores.latency_ms else None,
        "latency_p95_ms": scores.latency_ms.p95 if scores.latency_ms else None,
        "escalation_rate": report.two_stage.escalation_rate if report.two_stage else None,
        "screen_misses": report.two_stage.screen_misses if report.two_stage else None,
    }


def export_site(
    sets_root: Path = SETS_DIR,
    reports_dir: Path = DEFAULT_REPORTS_DIR,
    out: Path = SITE_DATA_DIR,
) -> ExportResult:
    items_by_set = _items_by_set(sets_root)
    runs: list[dict[str, Any]] = []
    produced: set[str] = set()
    folders = sorted(p for p in reports_dir.iterdir() if p.is_dir()) if reports_dir.is_dir() else []
    for folder in folders:
        if folder.name in UNPUBLISHED:
            continue
        for path in sorted(folder.glob("*.json")):
            report = Report.model_validate_json(path.read_text(encoding="utf-8"))
            run_id = path.stem
            if run_id in produced:
                raise ValueError(f"two reports share the run id {run_id}")
            produced.add(run_id)
            audio = report.audio is not None
            items = items_by_set.get(folder.name, {})
            _write(
                out / "runs" / f"{run_id}.json",
                {
                    "id": run_id,
                    "set": folder.name,
                    "configuration": _configuration(report),
                    "legacy": report.run.set_sha256 is None,
                    "audio": audio,
                    "run": report.run.model_dump(mode="json"),
                    "scores": report.scores.model_dump(mode="json"),
                    "by_provenance": {
                        k: v.model_dump(mode="json") for k, v in report.by_provenance.items()
                    },
                    "two_stage": report.two_stage.model_dump(mode="json")
                    if report.two_stage
                    else None,
                    "audio_scores": report.audio.model_dump(mode="json") if report.audio else None,
                    "items": [
                        _item_entry(d, items.get(d.item_id), report, audio) for d in report.items
                    ],
                },
            )
            runs.append({**_row(run_id, folder.name, report), "_audio": report.audio})

    results: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(runs, key=lambda r: (r["set"], r["configuration"], r["started_at"])):
        if row["_audio"] is not None:
            continue
        table = results.setdefault(row["set"], [])
        same = [i for i, r in enumerate(table) if r["configuration"] == row["configuration"]]
        clean = {k: v for k, v in row.items() if k != "_audio"}
        if not same:
            table.append(clean)
        elif not row["legacy"] or table[same[0]]["legacy"]:
            table[same[0]] = clean  # later wins; a set-pinned run beats a legacy one
    audio_rows: dict[str, dict[str, Any]] = {}
    for row in sorted(runs, key=lambda r: r["started_at"]):
        if row["_audio"] is not None:
            audio_rows[row["configuration"]] = {
                "run": row["run"],
                "configuration": row["configuration"],
                **row["_audio"].model_dump(mode="json"),
            }
    generators, labels = agreement(sets_root)
    summaries = summarize(sets_root)
    manifests = {s.name: load_manifest(s.name, sets_root) for s in summaries if s.error is None}
    _write(
        out / "index.json",
        {
            "sets": [
                {
                    **asdict(summary),
                    "description": manifests[summary.name].description
                    if summary.name in manifests
                    else "",
                    "kind": manifests[summary.name].kind if summary.name in manifests else None,
                }
                for summary in summaries
                if not summary.name.startswith("staging/")
            ],
            "results": results,
            "runs": sorted(
                ({k: v for k, v in r.items() if k != "_audio"} for r in runs),
                key=lambda r: (r["started_at"], r["run"]),
                reverse=True,
            ),
            "audio": [audio_rows[k] for k in sorted(audio_rows)],
            "agreement": {
                "generators": [asdict(row) for row in generators],
                "labels": [asdict(row) for row in labels],
            },
        },
    )
    removed = []
    for stale in sorted((out / "runs").glob("*.json")) if (out / "runs").is_dir() else []:
        if stale.stem not in produced:
            stale.unlink()
            removed.append(stale.name)
    return ExportResult(runs=len(runs), removed=removed)
