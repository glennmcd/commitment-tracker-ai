"""Evaluation audio: Polly and human clips pinned by SHA-256 in clips.jsonl, kept in a bucket."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from commitment_tracker.evaluation import cli
from commitment_tracker.evaluation.audio import (
    AudioSetError,
    add_human,
    fetch,
    load_clips,
    make_polly,
    upload,
)
from commitment_tracker.evaluation.sets import summarize
from commitment_tracker.evaluation.synthesis import wav_bytes
from commitment_tracker.settings import Settings
from tests.eval.test_dataset import item_data
from tests.eval.test_set_loading import write_set

SAMPLES_PER_CHAR = 50


def fake_synth(text: str, voice: str) -> bytes:
    return (b"\x01\x00" if voice == "Joanna" else b"\x02\x00") * (len(text) * SAMPLES_PER_CHAR)


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)


def dialogue(item_id: str) -> dict[str, Any]:
    texts = ["Can you send the deck?", "Sure, I'll send it Friday."]
    return item_data(
        id=item_id,
        turns=[{"speaker": "buyer", "text": texts[0]}, {"speaker": "seller", "text": texts[1]}],
        expected=[
            {"turn_index": 0, "label": "REQUEST", "quote": texts[0]},
            {**item_data()["expected"][0], "turn_index": 1, "quote": texts[1]},
        ],
        tags=["multi_turn"],
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    sets = tmp_path / "sets"
    write_set(sets, "test", [dialogue("t-01"), dialogue("t-02"), item_data(id="t-single")])
    audio = sets / "audio"
    audio.mkdir()
    manifest = {"name": "audio", "role": "test", "kind": "audio", "items_from": "test"}
    (audio / "set.json").write_text(json.dumps(manifest), encoding="utf-8")
    (audio / "clips.jsonl").write_text("", encoding="utf-8")
    return sets


def human_wav(tmp_path: Path, seconds: float = 1.0) -> Path:
    path = tmp_path / "recording.wav"
    path.write_bytes(wav_bytes(b"\x03\x00" * int(16_000 * seconds)))
    return path


def test_make_polly_writes_wavs_and_pins_them(tmp_path: Path, root: Path) -> None:
    audio_dir = tmp_path / ".audio"
    (clip,) = make_polly(["t-01"], root, audio_dir, fake_synth)
    data = (audio_dir / "t-01.wav").read_bytes()
    assert clip.sha256 == hashlib.sha256(data).hexdigest()
    assert (clip.source, clip.voices) == ("polly", {"buyer": "Joanna", "seller": "Matthew"})
    assert clip.duration_ms > 400  # two turns and the gap between them
    assert load_clips(root) == [clip]


def test_remaking_a_polly_clip_replaces_its_entry(tmp_path: Path, root: Path) -> None:
    make_polly(["t-01"], root, tmp_path / ".audio", fake_synth)
    make_polly(["t-01"], root, tmp_path / ".audio", fake_synth, voices=("Matthew", "Joanna"))
    (clip,) = load_clips(root)
    assert clip.voices == {"buyer": "Matthew", "seller": "Joanna"}


@pytest.mark.parametrize(
    ("item_id", "message"),
    [("t-99", "not in test"), ("t-single", "two speakers")],
)
def test_make_polly_rejects_unusable_items(
    tmp_path: Path, root: Path, item_id: str, message: str
) -> None:
    with pytest.raises(AudioSetError, match=message):
        make_polly([item_id], root, tmp_path / ".audio", fake_synth)


def test_add_human_records_readers_by_role_only(tmp_path: Path, root: Path) -> None:
    clip = add_human(
        "t-02",
        human_wav(tmp_path),
        {"buyer": "reader-1", "seller": "reader-2"},
        root,
        tmp_path / ".audio",
    )
    assert (clip.source, clip.duration_ms) == ("human", 1000)
    assert (tmp_path / ".audio" / "t-02.wav").is_file()
    assert load_clips(root)[0].voices == {"buyer": "reader-1", "seller": "reader-2"}


@pytest.mark.parametrize(
    ("readers", "message"),
    [
        ({"buyer": "Glenn", "seller": "reader-2"}, "reader-<n>"),
        ({"buyer": "reader-1"}, "every speaker"),
        ({"buyer": "reader-1", "seller": "reader-1"}, "two different readers"),
    ],
)
def test_add_human_rejects_bad_readers(
    tmp_path: Path, root: Path, readers: dict[str, str], message: str
) -> None:
    with pytest.raises(AudioSetError, match=message):
        add_human("t-02", human_wav(tmp_path), readers, root, tmp_path / ".audio")


def test_add_human_rejects_a_wav_in_the_wrong_format(tmp_path: Path, root: Path) -> None:
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"RIFF not really")
    with pytest.raises(AudioSetError, match="readable WAV"):
        add_human("t-02", bad, {"buyer": "reader-1", "seller": "reader-2"}, root, tmp_path)


def test_a_human_clip_is_never_overwritten_by_polly(tmp_path: Path, root: Path) -> None:
    readers = {"buyer": "reader-1", "seller": "reader-2"}
    add_human("t-02", human_wav(tmp_path), readers, root, tmp_path / ".audio")
    with pytest.raises(AudioSetError, match="human recording"):
        make_polly(["t-02"], root, tmp_path / ".audio", fake_synth)


def test_upload_then_fetch_round_trips_and_checks_hashes(tmp_path: Path, root: Path) -> None:
    store = FakeStore()
    make_polly(["t-01"], root, tmp_path / ".audio", fake_synth)
    assert upload(root, tmp_path / ".audio", store) == ["t-01"]
    fresh = tmp_path / "fresh"
    assert fetch(root, fresh, store) == ["t-01"]
    assert (fresh / "t-01.wav").read_bytes() == store.objects["clips/t-01.wav"]
    assert fetch(root, fresh, store) == []  # already there with the right hash


def test_fetch_refuses_a_clip_whose_hash_changed(tmp_path: Path, root: Path) -> None:
    store = FakeStore()
    make_polly(["t-01"], root, tmp_path / ".audio", fake_synth)
    upload(root, tmp_path / ".audio", store)
    store.objects["clips/t-01.wav"] = b"tampered"
    with pytest.raises(AudioSetError, match="t-01.*sha256"):
        fetch(root, tmp_path / "fresh", store)


def test_upload_refuses_a_local_file_that_does_not_match(tmp_path: Path, root: Path) -> None:
    make_polly(["t-01"], root, tmp_path / ".audio", fake_synth)
    (tmp_path / ".audio" / "t-01.wav").write_bytes(b"edited")
    with pytest.raises(AudioSetError, match="t-01.*sha256"):
        upload(root, tmp_path / ".audio", FakeStore())


def test_fetch_reports_a_missing_clip(tmp_path: Path, root: Path) -> None:
    make_polly(["t-01"], root, tmp_path / ".audio", fake_synth)
    with pytest.raises(AudioSetError, match="t-01 is not in the bucket"):
        fetch(root, tmp_path / "fresh", FakeStore())


def test_eval_sets_counts_clips_by_source(tmp_path: Path, root: Path) -> None:
    make_polly(["t-01"], root, tmp_path / ".audio", fake_synth)
    audio = next(s for s in summarize(root) if s.name == "audio")
    assert audio.error is None
    assert (audio.items, audio.provenance) == (1, {"polly": 1})


def test_cli_make_needs_a_profile_free_synthesizer(
    tmp_path: Path, root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "make_synthesizer", lambda profile, region: fake_synth)
    argv = ["make", "--item", "t-01", "--sets-dir", str(root), "--audio-dir", str(tmp_path / "a")]
    assert cli.audio_main(argv) == 0
    assert "t-01: polly" in capsys.readouterr().out


def test_cli_upload_without_a_bucket_names_the_setting(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("EVAL_AUDIO_BUCKET", raising=False)
    monkeypatch.setattr(cli, "Settings", lambda: Settings(_env_file=None))
    assert cli.audio_main(["upload", "--sets-dir", str(root)]) == 2
    assert "EVAL_AUDIO_BUCKET" in capsys.readouterr().err
