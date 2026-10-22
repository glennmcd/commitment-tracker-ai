"""JobWorker: Transcribe completion events and text jobs, on fakes (no network)."""

import asyncio
import logging
from collections.abc import Coroutine
from datetime import date
from typing import Any

import pytest

from commitment_tracker.extractor.errors import ModelUnavailable
from commitment_tracker.extractor.extractor import Extractor
from commitment_tracker.extractor.prompt import load_prompt
from commitment_tracker.jobs.memory import MemoryJobStore
from commitment_tracker.jobs.record import JobRecord, JobSource, JobStatus
from commitment_tracker.jobs.worker import JobWorker, TranscribeOutcome, parse_transcribe_event
from commitment_tracker.schemas import Turn
from commitment_tracker.transcription.fake import FakeTranscriber
from commitment_tracker.transcription.protocol import TimedTurn
from commitment_tracker.transcription.turns import TranscriptFormatError
from tests.fakes import FakeAdapter, FakeAudioStore, reply
from tests.test_api import GOOD_OUTPUT

JOB_ID = "1" * 64
KEY = f"uploads/{'a' * 32}.wav"
NOW = 1_761_000_000.0
TIMED = [
    TimedTurn(0, "Can you resend the invoice?", 0, 1_500),
    TimedTurn(1, "Sure, I'll do it this afternoon.", 1_900, 4_000),
]
SECRET = "pricing-is-42"


def run(coroutine: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coroutine)


class Ticker:
    """A clock that moves one second on every reading."""

    def __init__(self, start: float) -> None:
        self.now = start

    def __call__(self) -> float:
        self.now += 1.0
        return self.now


def make_job(**changes: Any) -> JobRecord:
    fields: dict[str, Any] = {
        "id": JOB_ID,
        "status": JobStatus.TRANSCRIBING,
        "source": JobSource.UPLOAD,
        "audio_key": KEY,
        "call_date": date(2026, 10, 21),
        "speaker_names": ["Ana", "Ben"],
        "created_at": int(NOW * 1000),
        "transcribing_at": int(NOW * 1000),
        "expires_at": int(NOW) + 3600,
    }
    return JobRecord(**(fields | changes))


class Rig:
    def __init__(
        self,
        *replies: Any,
        job: JobRecord | None = None,
        transcriber: FakeTranscriber | None = None,
    ) -> None:
        self.store = MemoryJobStore(clock=lambda: NOW)
        self.audio = FakeAudioStore()
        self.transcriber = transcriber or FakeTranscriber({JOB_ID: TIMED})
        self.adapter = FakeAdapter(*(replies or (reply(GOOD_OUTPUT),)))
        self.worker = JobWorker(
            self.store,
            self.audio,
            self.transcriber,
            Extractor(self.adapter, load_prompt("v1")),
            clock=Ticker(NOW),
        )
        self.job = job or make_job()
        self.store.create(self.job)

    def stored(self) -> JobRecord:
        job = self.store.get(JOB_ID)
        assert job is not None
        return job


def completed(job_id: str = JOB_ID) -> TranscribeOutcome:
    return TranscribeOutcome(job_id=job_id, completed=True)


# --- Transcribe events ---------------------------------------------------------------------------


def test_a_completed_job_is_analysed_and_cleaned_up() -> None:
    rig = Rig()

    run(rig.worker.on_transcribe(completed()))

    job = rig.stored()
    assert job.status is JobStatus.DONE
    assert job.turns == [
        Turn(speaker="Ana", text="Can you resend the invoice?", start_ms=0, end_ms=1_500),
        Turn(speaker="Ben", text="Sure, I'll do it this afternoon.", start_ms=1_900, end_ms=4_000),
    ]
    assert job.analysis is not None
    assert [span.label for span in job.analysis.spans] == ["COMMITMENT"]
    assert rig.audio.deleted == [KEY]
    assert rig.transcriber.deleted == [JOB_ID]


def test_stage_latencies_are_recorded() -> None:
    rig = Rig()

    run(rig.worker.on_transcribe(completed()))

    job = rig.stored()
    assert job.transcribed_at is not None
    assert job.analyzing_at is not None
    assert job.finished_at is not None
    assert job.transcribing_at is not None
    assert job.transcribing_at < job.transcribed_at <= job.analyzing_at < job.finished_at
    latency = job.latency()
    assert latency.transcribe_ms is not None and latency.transcribe_ms > 0
    assert latency.analyze_ms is not None and latency.analyze_ms > 0
    assert latency.total_ms is not None and latency.total_ms > 0


def test_default_speaker_names_apply_when_the_visitor_gave_none() -> None:
    rig = Rig(job=make_job(speaker_names=[]))

    run(rig.worker.on_transcribe(completed()))

    assert [t.speaker for t in rig.stored().turns or []] == ["Speaker 1", "Speaker 2"]


def test_a_sample_clip_is_never_deleted() -> None:
    rig = Rig(job=make_job(source=JobSource.SAMPLE, audio_key="samples/invoice.wav"))

    run(rig.worker.on_transcribe(completed()))

    assert rig.stored().status is JobStatus.DONE
    assert rig.audio.deleted == []
    assert rig.transcriber.deleted == [JOB_ID]  # the Transcribe output and job still go


def test_a_failed_transcription_fails_the_job_and_cleans_up() -> None:
    rig = Rig()

    run(rig.worker.on_transcribe(TranscribeOutcome(job_id=JOB_ID, completed=False)))

    job = rig.stored()
    assert job.status is JobStatus.FAILED
    assert job.error_code == "transcription_failed"
    assert job.finished_at is not None
    assert rig.adapter.requests == []
    assert rig.audio.deleted == [KEY]
    assert rig.transcriber.deleted == [JOB_ID]


@pytest.mark.parametrize("status", [JobStatus.ANALYZING, JobStatus.DONE, JobStatus.FAILED])
def test_an_event_for_a_job_that_moved_on_is_ignored(status: JobStatus) -> None:
    rig = Rig(job=make_job(status=status))

    run(rig.worker.on_transcribe(completed()))

    assert rig.stored().status is status
    assert rig.adapter.requests == []
    assert rig.audio.deleted == []
    assert rig.transcriber.deleted == []


def test_an_event_for_an_unknown_job_is_ignored() -> None:
    rig = Rig()

    run(rig.worker.on_transcribe(completed("2" * 64)))

    assert rig.stored().status is JobStatus.TRANSCRIBING
    assert rig.adapter.requests == []


def test_a_redelivered_event_analyses_once() -> None:
    rig = Rig()

    run(rig.worker.on_transcribe(completed()))
    run(rig.worker.on_transcribe(completed()))

    assert len(rig.adapter.requests) == 1
    assert rig.stored().status is JobStatus.DONE


@pytest.mark.parametrize(
    "transcriber",
    [FakeTranscriber(), FakeTranscriber({JOB_ID: []})],
    ids=["no-output", "no-speech"],
)
def test_output_that_is_missing_or_silent_fails_the_job(transcriber: FakeTranscriber) -> None:
    rig = Rig(transcriber=transcriber)

    run(rig.worker.on_transcribe(completed()))

    job = rig.stored()
    assert job.status is JobStatus.FAILED
    assert job.error_code == ("transcription_failed" if not transcriber.results else "no_speech")
    assert rig.adapter.requests == []
    assert rig.audio.deleted == [KEY]


def test_unreadable_output_fails_the_job() -> None:
    class Garbled(FakeTranscriber):
        def result(self, job_id: str) -> list[TimedTurn]:
            raise TranscriptFormatError("unexpected Transcribe output")

    rig = Rig(transcriber=Garbled())

    run(rig.worker.on_transcribe(completed()))

    assert rig.stored().error_code == "transcription_failed"
    assert rig.audio.deleted == [KEY]


def test_a_cleanup_failure_does_not_fail_the_job() -> None:
    class Stuck(FakeTranscriber):
        def delete(self, job_id: str) -> None:
            raise RuntimeError("throttled")

    rig = Rig(transcriber=Stuck({JOB_ID: TIMED}))

    run(rig.worker.on_transcribe(completed()))

    assert rig.stored().status is JobStatus.DONE
    assert rig.audio.deleted == [KEY]


# --- Model failures ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("replies", "code"),
    [
        ([ModelUnavailable("down")], "model_unavailable"),
        ([reply("", stop_reason="refusal", refusal_category="cyber")], "model_refused"),
        ([reply("not json"), reply("still not json")], "model_output_invalid"),
        ([RuntimeError("bug")], "analysis_failed"),
    ],
    ids=["unavailable", "refused", "invalid-twice", "unexpected"],
)
def test_a_model_failure_fails_the_job_with_its_code(replies: list[Any], code: str) -> None:
    rig = Rig(*replies)

    run(rig.worker.on_transcribe(completed()))

    job = rig.stored()
    assert job.status is JobStatus.FAILED
    assert job.error_code == code
    assert job.analysis is None
    assert job.turns is not None  # the transcript is kept for the visitor
    assert rig.audio.deleted == [KEY]  # the audio goes before the model is called


# --- Text jobs -----------------------------------------------------------------------------------

TEXT = [
    Turn(speaker="A", text="Can you resend the invoice?"),
    Turn(speaker="B", text="Sure, I'll do it this afternoon."),
]


def text_job(**changes: Any) -> JobRecord:
    fields: dict[str, Any] = {
        "status": JobStatus.UPLOADED,
        "source": JobSource.TRANSCRIPT,
        "audio_key": None,
        "speaker_names": [],
        "turns": TEXT,
        "transcribing_at": None,
    }
    return make_job(**(fields | changes))


def test_a_text_job_is_analysed_without_touching_storage() -> None:
    rig = Rig(job=text_job())

    run(rig.worker.on_text_job(JOB_ID))

    job = rig.stored()
    assert job.status is JobStatus.DONE
    assert job.analysis is not None
    assert job.turns == TEXT
    assert job.transcribed_at is None
    assert rig.audio.deleted == []
    assert rig.transcriber.deleted == []
    assert job.latency().transcribe_ms is None
    assert job.latency().analyze_ms is not None


def test_a_text_job_that_fails_reports_the_model_error() -> None:
    rig = Rig(ModelUnavailable("down"), job=text_job())

    run(rig.worker.on_text_job(JOB_ID))

    assert rig.stored().error_code == "model_unavailable"


@pytest.mark.parametrize("status", [JobStatus.ANALYZING, JobStatus.DONE, JobStatus.FAILED])
def test_a_text_job_that_moved_on_is_ignored(status: JobStatus) -> None:
    rig = Rig(job=text_job(status=status))

    run(rig.worker.on_text_job(JOB_ID))

    assert rig.stored().status is status
    assert rig.adapter.requests == []


def test_an_unknown_text_job_is_ignored() -> None:
    rig = Rig(job=text_job())
    run(rig.worker.on_text_job("2" * 64))
    assert rig.adapter.requests == []


def test_only_text_jobs_run_from_a_direct_invoke() -> None:
    """An audio job sits in `transcribing`; a stray invoke must not start analysing it."""
    rig = Rig()

    run(rig.worker.on_text_job(JOB_ID))

    assert rig.stored().status is JobStatus.TRANSCRIBING
    assert rig.adapter.requests == []


# --- Events --------------------------------------------------------------------------------------


def event(name: str = f"ct-{JOB_ID}", status: str = "COMPLETED") -> dict[str, Any]:
    return {
        "source": "aws.transcribe",
        "detail-type": "Transcribe Job State Change",
        "detail": {"TranscriptionJobName": name, "TranscriptionJobStatus": status},
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (event(), TranscribeOutcome(JOB_ID, completed=True)),
        (event(status="FAILED"), TranscribeOutcome(JOB_ID, completed=False)),
    ],
)
def test_it_reads_completion_events(raw: dict[str, Any], expected: TranscribeOutcome) -> None:
    assert parse_transcribe_event(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        event(status="IN_PROGRESS"),
        event(name="other-job"),
        event(name=f"ct-{'Z' * 64}"),
        event(name="ct-short"),
        {"detail": {}},
        {},
        {"detail": "text"},
    ],
    ids=["in-progress", "foreign-name", "bad-id", "short-id", "empty-detail", "empty", "not-a-map"],
)
def test_it_ignores_other_events(raw: dict[str, Any]) -> None:
    assert parse_transcribe_event(raw) is None


# --- Logging -------------------------------------------------------------------------------------


def test_the_worker_logs_no_transcript_text(caplog: pytest.LogCaptureFixture) -> None:
    transcriber = FakeTranscriber(
        {
            JOB_ID: [
                TimedTurn(0, f"The code is {SECRET}.", 0, 900),
                TimedTurn(1, "Noted.", 1_000, 1_500),
            ]
        }
    )
    rig = Rig(reply("not json"), reply("still not json"), transcriber=transcriber)

    with caplog.at_level(logging.DEBUG):
        run(rig.worker.on_transcribe(completed()))

    assert SECRET not in caplog.text
