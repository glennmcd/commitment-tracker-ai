"""scripts/make_samples.py: dialogues to Polly speech to WAVs, with a fake Polly (no network)."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from commitment_tracker.evaluation.dataset import load_dataset
from commitment_tracker.jobs.audio import validate_wav
from commitment_tracker.jobs.samples import SampleClip, load_catalog
from commitment_tracker.schemas import Label

BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "make_samples.py"
DIALOGUES = BACKEND / "samples" / "dialogues.jsonl"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_samples", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_samples"] = module
    spec.loader.exec_module(module)
    return module


script = load_script()
SAMPLES_PER_CHAR = 100  # the fake voice says one character in 100 samples (6.25 ms)


def fake_synth(text: str, voice: str) -> bytes:
    return b"\x01\x00" * (len(text) * SAMPLES_PER_CHAR)


class FakePolly:
    def __init__(self, stream: bytes | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._stream = stream

    def synthesize_speech(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        data = self._stream if self._stream is not None else fake_synth(kwargs["Text"], "")
        return {"AudioStream": io.BytesIO(data)}


# --- The committed dialogues ---------------------------------------------------------------------


def committed() -> list[Any]:
    dialogues: list[Any] = script.load_dialogues(DIALOGUES)
    return dialogues


def test_the_committed_dialogues_load() -> None:
    dialogues = committed()
    assert [d.id for d in dialogues] == [
        "onboarding-paperwork",
        "security-review",
        "export-feature-sync",
        "renewal-pricing",
    ]


def test_each_dialogue_has_two_speakers_and_two_different_voices() -> None:
    for dialogue in committed():
        assert len({turn.speaker for turn in dialogue.turns}) == 2
        assert len(set(dialogue.voices)) == 2


def test_the_first_speaker_gets_the_first_voice() -> None:
    for dialogue in committed():
        voices = script.speaker_voices(dialogue)
        assert voices[dialogue.turns[0].speaker] == dialogue.voices[0]
        assert sorted(voices.values()) == sorted(dialogue.voices)


def test_each_dialogue_is_sized_for_a_clip_of_thirty_to_sixty_seconds() -> None:
    """Polly speaks about 14 characters a second, so this is roughly 30 to 60 seconds."""
    for dialogue in committed():
        chars = sum(len(turn.text) for turn in dialogue.turns)
        assert 400 <= chars <= 800, dialogue.id


def test_together_the_dialogues_cover_every_ledger_label_and_the_near_misses() -> None:
    labels = {span.label for dialogue in committed() for span in dialogue.expected}
    assert labels >= {
        Label.COMMITMENT,
        Label.HEDGED,
        Label.CONDITIONAL,
        Label.REQUEST,
        Label.REFUSAL,
        Label.REPORTED,
        Label.SUGGESTION,
    }


def test_the_dialogues_are_new_text_not_dev_set_utterances() -> None:
    dev = (BACKEND / "eval" / "sets" / "dev" / "items.jsonl").read_text(encoding="utf-8")
    for dialogue in committed():
        for turn in dialogue.turns:
            assert turn.text not in dev


def test_a_dialogue_with_a_quote_not_in_its_turn_is_rejected(tmp_path: Path) -> None:
    line = json.loads(DIALOGUES.read_text(encoding="utf-8").splitlines()[0])
    line["expected"][0]["quote"] = "words nobody said"
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="quote"):
        script.load_dialogues(path)


def test_three_speakers_are_rejected(tmp_path: Path) -> None:
    line = json.loads(DIALOGUES.read_text(encoding="utf-8").splitlines()[0])
    line["turns"][1]["speaker"] = "Third"
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="two speakers"):
        script.load_dialogues(path)


# --- Building a clip -----------------------------------------------------------------------------


def test_turn_times_come_from_sample_counts_with_a_gap_between_turns() -> None:
    dialogue = committed()[0]

    clip = script.build_clip(dialogue, fake_synth)

    first, second = clip.turns[0], clip.turns[1]
    first_ms = len(dialogue.turns[0].text) * SAMPLES_PER_CHAR * 1000 // 16_000
    assert (first.start_ms, first.end_ms) == (0, first_ms)
    assert second.start_ms == first_ms + 400
    assert [t.text for t in clip.turns] == [t.text for t in dialogue.turns]
    assert [t.speaker for t in clip.turns] == [t.speaker for t in dialogue.turns]


def test_turns_are_joined_by_exactly_four_hundred_milliseconds_of_silence() -> None:
    dialogue = committed()[0]
    clip = script.build_clip(dialogue, fake_synth)

    silence = b"\x00\x00" * 6_400
    first = fake_synth(dialogue.turns[0].text, "")
    assert clip.pcm.startswith(first + silence)
    assert len(clip.pcm) == (
        sum(len(fake_synth(t.text, "")) for t in dialogue.turns)
        + len(silence) * (len(dialogue.turns) - 1)
    )


def test_each_turn_is_spoken_by_its_speakers_voice() -> None:
    dialogue = committed()[3]  # Omar speaks first, with the first voice listed
    heard: list[tuple[str, str]] = []

    def synth(text: str, voice: str) -> bytes:
        heard.append((text, voice))
        return fake_synth(text, voice)

    script.build_clip(dialogue, synth)

    voices = script.speaker_voices(dialogue)
    assert heard == [(t.text, voices[t.speaker]) for t in dialogue.turns]


def test_the_wav_is_the_upload_format_and_matches_the_timeline() -> None:
    clip = script.build_clip(committed()[0], fake_synth)

    info = validate_wav(script.wav_bytes(clip.pcm))

    assert info.duration_ms == clip.duration_ms
    assert clip.turns[-1].end_ms == clip.duration_ms


def test_a_clip_over_sixty_seconds_is_rejected_by_name() -> None:
    def long_synth(text: str, voice: str) -> bytes:
        return b"\x01\x00" * 16_000 * 20

    with pytest.raises(ValueError, match="onboarding-paperwork"):
        script.build_clip(committed()[0], long_synth)


# --- Polly ---------------------------------------------------------------------------------------


def test_polly_is_asked_for_standard_16khz_pcm() -> None:
    polly = FakePolly()

    pcm = script.polly_synthesizer(polly)("Hello there.", "Joanna")

    assert pcm == fake_synth("Hello there.", "")
    assert polly.calls == [
        {
            "Engine": "standard",
            "OutputFormat": "pcm",
            "SampleRate": "16000",
            "TextType": "text",
            "VoiceId": "Joanna",
            "Text": "Hello there.",
        }
    ]


def test_a_stream_that_is_not_whole_samples_is_rejected() -> None:
    with pytest.raises(ValueError, match="16-bit"):
        script.polly_synthesizer(FakePolly(stream=b"\x00\x01\x02"))("Hi.", "Joanna")


# --- Outputs -------------------------------------------------------------------------------------


def run(tmp_path: Path, polly: FakePolly | None = None, *extra: str) -> int:
    args = [
        "--wav-dir",
        str(tmp_path / "wav"),
        "--manifest",
        str(tmp_path / "samples.json"),
        "--truth",
        str(tmp_path / "ground-truth.jsonl"),
        *extra,
    ]
    code: int = script.main(args, polly=polly)
    return code


def test_a_run_writes_wavs_a_manifest_and_ground_truth(tmp_path: Path) -> None:
    polly = FakePolly()

    assert run(tmp_path, polly) == 0

    catalog = load_catalog(tmp_path / "samples.json")
    clips: list[SampleClip] = catalog.all()
    assert [c.id for c in clips] == [d.id for d in committed()]
    for clip in clips:
        data = (tmp_path / "wav" / f"{clip.id}.wav").read_bytes()
        assert validate_wav(data).duration_ms == clip.duration_ms
        import hashlib

        assert hashlib.sha256(data).hexdigest() == clip.sha256
    truth = load_dataset(tmp_path / "ground-truth.jsonl")
    assert [item.id for item in truth] == [c.id for c in clips]
    assert all(t.start_ms is not None and t.end_ms is not None for t in truth[0].turns)
    assert len(polly.calls) == sum(len(d.turns) for d in committed())


def test_the_ground_truth_keeps_the_expected_spans(tmp_path: Path) -> None:
    run(tmp_path, FakePolly())

    truth = load_dataset(tmp_path / "ground-truth.jsonl")

    for item, dialogue in zip(truth, committed(), strict=True):
        assert item.expected == dialogue.expected
        assert item.call_date == dialogue.call_date


def test_a_dry_run_calls_nothing_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    polly = FakePolly()

    assert run(tmp_path, polly, "--dry-run") == 0

    assert polly.calls == []
    assert not (tmp_path / "wav").exists()
    out = capsys.readouterr().out
    assert "onboarding-paperwork" in out
    assert "$" in out  # the estimated cost
