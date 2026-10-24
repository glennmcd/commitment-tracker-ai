"""Scoring transcribed audio: align transcribed turns to the item, score, compare with text."""

import json
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.audio import AudioClip, make_polly
from commitment_tracker.evaluation.audio_eval import (
    AwsClipTranscriber,
    TranscriptCache,
    align,
    audio_scores,
)
from commitment_tracker.evaluation.dataset import EvalItem
from commitment_tracker.evaluation.results import ItemResult
from commitment_tracker.transcription.protocol import TimedTurn
from tests.eval.builders import pred, response
from tests.eval.test_audio_clips import dialogue, fake_synth
from tests.eval.test_dataset import item_data
from tests.eval.test_set_loading import write_set

ITEM = EvalItem.model_validate(dialogue("t-01"))  # buyer asks, seller commits


def timed(*turns: tuple[int, str]) -> list[TimedTurn]:
    return [
        TimedTurn(speaker=s, text=t, start_ms=i * 1000, end_ms=i * 1000 + 900)
        for i, (s, t) in enumerate(turns)
    ]


def test_a_faithful_transcript_aligns_one_to_one() -> None:
    result = align(ITEM, timed((0, "Can you send the deck?"), (1, "Sure, I'll send it Friday.")))
    assert [t.speaker for t in result.item.turns] == ["buyer", "seller"]
    assert [s.turn_index for s in result.item.expected] == [0, 1]
    assert (result.turn_mismatch, result.speaker_errors, result.unmatched_spans) == (False, 0, 0)


def test_speaker_numbers_map_to_roles_by_majority() -> None:
    # Transcribe numbers voices in order of first speech; here the seller happened to be "0".
    item = EvalItem.model_validate(
        dialogue("t-01")
        | {
            "turns": [
                {"speaker": "seller", "text": "Sure, I'll send it Friday."},
                {"speaker": "buyer", "text": "Can you send the deck?"},
            ],
            "expected": [
                {
                    **item_data()["expected"][0],
                    "turn_index": 0,
                    "quote": "Sure, I'll send it Friday.",
                },
            ],
        }
    )
    result = align(item, timed((0, "Sure, I'll send it Friday."), (1, "Can you send the deck?")))
    assert [t.speaker for t in result.item.turns] == ["seller", "buyer"]


def test_asr_slips_still_align_and_keep_the_expected_quotes() -> None:
    result = align(ITEM, timed((0, "can you send a deck"), (1, "sure ill send it friday")))
    assert [s.turn_index for s in result.item.expected] == [0, 1]
    assert result.item.expected[1].quote == "Sure, I'll send it Friday."


def test_a_split_turn_maps_the_span_to_the_piece_holding_its_words() -> None:
    result = align(
        ITEM,
        timed((0, "Can you send the deck?"), (1, "Sure."), (1, "I'll send it Friday.")),
    )
    assert result.turn_mismatch
    assert result.item.expected[1].turn_index == 2


def test_a_misattributed_turn_counts_as_a_speaker_error() -> None:
    three = EvalItem.model_validate(
        dialogue("t-01")
        | {
            "turns": [
                {"speaker": "buyer", "text": "Can you send the deck?"},
                {"speaker": "seller", "text": "Sure, I'll send it Friday."},
                {"speaker": "buyer", "text": "Great, thanks a lot."},
            ]
        }
    )
    result = align(
        three,
        timed(
            (0, "Can you send the deck?"),
            (1, "Sure, I'll send it Friday."),
            (1, "Great, thanks a lot."),
        ),
    )
    assert result.speaker_errors == 1


def test_a_span_whose_turn_vanished_is_unmatched() -> None:
    result = align(ITEM, timed((0, "Can you send the deck?")))
    assert result.unmatched_spans == 1
    assert result.item.expected[1].turn_index == -1


def test_the_penalty_is_audio_minus_text_per_source() -> None:
    clips = {
        "t-01": AudioClip(
            test_item_id="t-01", source="polly", voices={}, duration_ms=1, sha256="a" * 64
        )
    }
    good = response(pred(1, "COMMITMENT", "Sure, I'll send it Friday."))
    missed = response(pred(1, "NONE", "Sure, I'll send it Friday."))
    alignment = align(ITEM, timed((0, "Can you send the deck?"), (1, "Sure, I'll send it Friday.")))
    scores = audio_scores(
        clips,
        {"t-01": alignment},
        [ItemResult(alignment.item, missed, None, False)],
        [ItemResult(ITEM, good, None, False)],
        text_sha256="f" * 64,
    )
    polly = scores.slices["polly"]
    assert (polly.ledger_f1_audio, polly.ledger_f1_text, polly.penalty) == (0.0, 1.0, -1.0)
    assert scores.slices["all"].clips == 1


def test_the_transcript_cache_is_keyed_by_audio_hash(tmp_path: Path) -> None:
    cache = TranscriptCache(tmp_path)
    turns = timed((0, "Hello."))
    assert cache.get("a" * 64) is None
    cache.put("a" * 64, turns)
    assert cache.get("a" * 64) == turns


class FakeTranscribe:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = statuses
        self.started: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def start_transcription_job(self, **kwargs: Any) -> None:
        self.started.append(kwargs)

    def get_transcription_job(self, TranscriptionJobName: str) -> dict[str, Any]:  # noqa: N803
        status = self.statuses.pop(0)
        return {"TranscriptionJob": {"TranscriptionJobStatus": status, "FailureReason": "bad"}}

    def delete_transcription_job(self, TranscriptionJobName: str) -> None:  # noqa: N803
        self.deleted.append(TranscriptionJobName)


class FakeS3:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = json.dumps(body).encode()
        self.deleted: list[str] = []

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        class Body:
            def __init__(self, data: bytes) -> None:
                self.data = data

            def read(self) -> bytes:
                return self.data

        return {"Body": Body(self.body)}

    def delete_object(self, Bucket: str, Key: str) -> None:  # noqa: N803
        self.deleted.append(Key)


TRANSCRIBE_OUTPUT = {
    "results": {
        "items": [
            {
                "type": "pronunciation",
                "start_time": "0.0",
                "end_time": "0.5",
                "speaker_label": "spk_0",
                "alternatives": [{"content": "Hello"}],
            }
        ]
    }
}


def clip() -> AudioClip:
    return AudioClip(test_item_id="t-01", source="polly", voices={}, duration_ms=1, sha256="b" * 64)


def test_the_aws_transcriber_uses_its_own_job_prefix_and_cleans_up() -> None:
    transcribe, s3 = FakeTranscribe(["IN_PROGRESS", "COMPLETED"]), FakeS3(TRANSCRIBE_OUTPUT)
    transcriber = AwsClipTranscriber(transcribe, s3, "eval-bucket", sleep=lambda _: None)
    turns = transcriber(clip())
    assert [t.text for t in turns] == ["Hello"]
    (started,) = transcribe.started
    # Not "ct-": the stack's EventBridge rule would hand a ct- job to the demo worker.
    assert started["TranscriptionJobName"].startswith("eval-")
    assert started["Media"] == {"MediaFileUri": "s3://eval-bucket/clips/t-01.wav"}
    assert transcribe.deleted == [started["TranscriptionJobName"]]
    assert s3.deleted == [started["OutputKey"]]


def test_a_failed_transcription_job_raises() -> None:
    transcriber = AwsClipTranscriber(
        FakeTranscribe(["FAILED"]), FakeS3(TRANSCRIBE_OUTPUT), "b", sleep=lambda _: None
    )
    with pytest.raises(RuntimeError, match="bad"):
        transcriber(clip())


# --- the CLI end to end --------------------------------------------------------------------------


def audio_repo(tmp_path: Path) -> Path:
    sets = tmp_path / "sets"
    write_set(sets, "test", [dialogue("t-01")])
    audio = sets / "audio"
    audio.mkdir()
    manifest = {"name": "audio", "role": "test", "kind": "audio", "items_from": "test"}
    (audio / "set.json").write_text(json.dumps(manifest), encoding="utf-8")
    (audio / "clips.jsonl").write_text("", encoding="utf-8")
    make_polly(["t-01"], sets, tmp_path / ".audio", fake_synth)
    return sets


def run_audio(tmp_path: Path, sets: Path, *extra: str) -> int:
    return cli.main(
        [
            "--set",
            "audio",
            "--transcribe",
            "--sets-dir",
            str(sets),
            "--reports-dir",
            str(tmp_path / "reports"),
            "--cache-dir",
            str(tmp_path / "cache"),
            *extra,
        ]
    )


def test_cli_scores_audio_and_reports_the_penalty(
    tmp_path: Path, fake_model: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    sets = audio_repo(tmp_path)
    calls: list[str] = []

    def transcriber(profile: str | None, region: str, bucket: str | None) -> Any:
        def transcribe(c: AudioClip) -> list[TimedTurn]:
            calls.append(c.test_item_id)
            return timed((0, "Can you send the deck?"), (1, "Sure, I'll send it Friday."))

        return transcribe

    monkeypatch.setattr(cli, "make_transcriber", transcriber)
    assert run_audio(tmp_path, sets) == 0
    assert run_audio(tmp_path, sets) == 0
    assert calls == ["t-01"]  # the second run reads the transcript cache
    (report,) = sorted((tmp_path / "reports" / "audio").glob("*.json"))[-1:]
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["run"]["set_name"] == "audio"
    assert set(data["audio"]["slices"]) == {"polly", "all"}
    assert data["audio"]["turn_mismatches"] == 0
    transcript = data["items"][0]["transcript"]
    assert [turn["speaker"] for turn in transcript] == ["buyer", "seller"]


def test_cli_audio_offline_needs_every_transcript_cached(
    tmp_path: Path, fake_model: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    sets = audio_repo(tmp_path)
    assert run_audio(tmp_path, sets, "--offline") == 1
    assert "1 clips have no cached transcript" in capsys.readouterr().err


def test_an_audio_set_needs_transcribe(
    tmp_path: Path, fake_model: list[tuple[str, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    sets = audio_repo(tmp_path)
    argv = ["--set", "audio", "--sets-dir", str(sets), "--reports-dir", str(tmp_path / "r")]
    assert cli.main(argv) == 2
    assert "--transcribe" in capsys.readouterr().err


def test_a_short_turn_maps_in_order_not_to_an_earlier_turn_sharing_its_words() -> None:
    four = EvalItem.model_validate(
        dialogue("t-01")
        | {
            "turns": [
                {"speaker": "buyer", "text": "Okay, can you send the report?"},
                {"speaker": "seller", "text": "Sure, I'll send it Friday."},
                {"speaker": "buyer", "text": "Okay."},
                {"speaker": "seller", "text": "Send the report?"},
            ],
            "expected": [
                {
                    **item_data()["expected"][0],
                    "turn_index": 1,
                    "quote": "Sure, I'll send it Friday.",
                }
            ],
        }
    )
    result = align(
        four,
        timed(
            (0, "Okay, can you send the report?"),
            (1, "Sure, I'll send it Friday."),
            (0, "Okay."),
            (1, "Send the report?"),
        ),
    )
    assert [t.speaker for t in result.item.turns] == ["buyer", "seller", "buyer", "seller"]
    assert (result.speaker_errors, result.unmatched_spans) == (0, 0)
    assert result.item.expected[0].turn_index == 1
