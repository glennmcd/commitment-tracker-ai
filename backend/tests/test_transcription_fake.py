"""The fake transcriber used by the job and worker tests: recorded starts, scripted results."""

import pytest

from commitment_tracker.transcription.fake import FakeTranscriber
from commitment_tracker.transcription.protocol import AudioRef, TimedTurn, Transcriber

AUDIO = AudioRef(bucket="audio-bucket", key="uploads/abc.wav")
TURNS = [TimedTurn(speaker=0, text="Hello.", start_ms=0, end_ms=400)]


def test_records_started_jobs() -> None:
    transcriber: Transcriber = FakeTranscriber()

    transcriber.start(AUDIO, "ct-1")

    assert isinstance(transcriber, FakeTranscriber)
    assert transcriber.started == [(AUDIO, "ct-1")]


def test_returns_scripted_results() -> None:
    transcriber = FakeTranscriber({"ct-1": TURNS})

    assert transcriber.result("ct-1") == TURNS


def test_result_is_a_copy() -> None:
    transcriber = FakeTranscriber({"ct-1": TURNS})

    transcriber.result("ct-1").clear()

    assert transcriber.result("ct-1") == TURNS


def test_unknown_job_raises() -> None:
    with pytest.raises(LookupError):
        FakeTranscriber().result("ct-missing")


def test_audio_ref_uri() -> None:
    assert AUDIO.uri == "s3://audio-bucket/uploads/abc.wav"
