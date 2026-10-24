"""`uv run eval promote` and the review agreement summary (`eval-sets --agreement`)."""

import json
from datetime import date
from pathlib import Path

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.agreement import agreement
from commitment_tracker.evaluation.importer import import_batch
from commitment_tracker.evaluation.promote import PromoteError, promote_batch
from commitment_tracker.evaluation.review import review_batch
from commitment_tracker.evaluation.sets import load_set
from tests.eval.test_review import Terminal, stage, two_span_draft
from tests.eval.test_set_loading import write_set

TODAY = date(2026, 10, 26)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    sets = tmp_path / "sets"
    write_set(sets, "dev", [], role="dev", gated=False)
    write_set(sets, "test", [])
    return sets


def reviewed(tmp_path: Path, root: Path, *answers: str) -> None:
    """Stage three items and review them with `answers`."""
    stage(
        tmp_path,
        root,
        two_span_draft("gem01-01", "deck"),
        two_span_draft("gem01-02", "contract"),
        two_span_draft("gem01-03", "invoice"),
    )
    review_batch("gem01", root, Terminal(*answers).io())


# accept, take mine (edited), reject
ANSWERS = ("r", "c", "", "r", "h", "m", "n", "c", "r")


def test_accepted_and_edited_items_move_to_the_target(tmp_path: Path, root: Path) -> None:
    reviewed(tmp_path, root, *ANSWERS)
    result = promote_batch("gem01", "test", root, today=TODAY)
    assert result.promoted == ["gem01-01", "gem01-02"]
    test = load_set("test", root)
    assert [item.id for item in test.items] == ["gem01-01", "gem01-02"]
    assert {item.review for item in test.items} == {"accepted", "edited"}
    assert result.sha256 == test.sha256
    (source,) = test.manifest.sources
    assert (source.batch, source.provenance, source.items) == ("gem01", "gemini-3-pro", 2)
    assert (source.imported, source.promoted) == (date(2026, 10, 24), TODAY)
    assert source.generation_prompt == "prompt-v1"


def test_rejected_items_and_the_review_log_stay_in_staging(tmp_path: Path, root: Path) -> None:
    reviewed(tmp_path, root, *ANSWERS)
    promote_batch("gem01", "test", root, today=TODAY)
    staging = load_set("staging/gem01", root, allow_empty=True)
    assert [item.id for item in staging.items] == ["gem01-03"]
    assert (root / "staging" / "gem01" / "review.jsonl").is_file()


def test_promoting_again_finds_nothing(tmp_path: Path, root: Path) -> None:
    reviewed(tmp_path, root, *ANSWERS)
    promote_batch("gem01", "test", root, today=TODAY)
    with pytest.raises(PromoteError, match="nothing to promote"):
        promote_batch("gem01", "test", root, today=TODAY)


def test_an_unfinished_review_blocks_promotion(tmp_path: Path, root: Path) -> None:
    reviewed(tmp_path, root, "r", "c", "", "q")
    with pytest.raises(PromoteError, match="2 items are not reviewed yet"):
        promote_batch("gem01", "test", root, today=TODAY)


@pytest.mark.parametrize(
    ("target", "message"),
    [("staging/gem02", "staging"), ("nope", "no set named 'nope'")],
)
def test_the_target_must_be_an_existing_set(
    tmp_path: Path, root: Path, target: str, message: str
) -> None:
    reviewed(tmp_path, root, *ANSWERS)
    with pytest.raises((PromoteError, ValueError), match=message):
        promote_batch("gem01", target, root, today=TODAY)


def test_claude_drafts_never_reach_a_test_set(tmp_path: Path, root: Path) -> None:
    source = tmp_path / "reply.jsonl"
    source.write_text(json.dumps(two_span_draft("cla01-01")) + "\n", encoding="utf-8")
    import_batch(
        source,
        batch="cla01",
        provenance="claude-opus-5-5",
        generation_prompt="prompt-v1",
        root=root,
        today=TODAY,
    )
    review_batch("cla01", root, Terminal("r", "c", "").io())
    with pytest.raises(PromoteError, match="Claude"):
        promote_batch("cla01", "test", root, today=TODAY)
    assert promote_batch("cla01", "dev", root, today=TODAY).promoted == ["cla01-01"]


def test_cli_promote_into_a_gated_set_asks_for_a_new_baseline(
    tmp_path: Path, root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewed(tmp_path, root, *ANSWERS)
    argv = ["promote", "--batch", "gem01", "--to", "test", "--sets-dir", str(root)]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "promoted 2" in out
    assert "new report and baseline" in out


# --- agreement -----------------------------------------------------------------------------------


def test_agreement_by_generator_and_label(tmp_path: Path, root: Path) -> None:
    reviewed(tmp_path, root, *ANSWERS)
    by_generator, by_label = agreement(root)
    gemini, overall = by_generator
    # six spans: REQUEST/COMMITMENT agreed on items 1 and 2's first span; 2 disagreements
    assert (gemini.key, gemini.spans) == ("gemini-3-pro", 6)
    assert gemini.agreement == pytest.approx(4 / 6)
    assert gemini.kappa is not None
    assert overall.key == "all"
    labels = {row.key: row for row in by_label}
    assert labels["REQUEST"].agreement == pytest.approx(2 / 3)
    assert labels["COMMITMENT"].agreement == pytest.approx(2 / 3)


def test_agreement_with_no_reviews_is_empty(root: Path) -> None:
    assert agreement(root) == ([], [])


def test_eval_sets_agreement_flag(
    tmp_path: Path, root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewed(tmp_path, root, *ANSWERS)
    assert cli.sets_main(["--sets-dir", str(root), "--agreement"]) == 0
    out = capsys.readouterr().out
    assert "gemini-3-pro" in out and "kappa" in out
    assert "COMMITMENT" in out
