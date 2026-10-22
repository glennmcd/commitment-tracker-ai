"""JobService: starting jobs from uploads, samples and text, with deduplication and failures."""

from datetime import date

import pytest

from commitment_tracker.jobs.audio import AudioInvalid, AudioTooLong
from commitment_tracker.jobs.memory import MemoryJobStore
from commitment_tracker.jobs.record import JobSource, JobStatus
from commitment_tracker.jobs.samples import SampleCatalog, SampleClip
from commitment_tracker.jobs.service import (
    JobService,
    SampleNotFound,
    TextJobsUnavailable,
    UploadNotFound,
    job_id_for,
)
from commitment_tracker.schemas import Turn
from commitment_tracker.transcription.fake import FakeTranscriber
from commitment_tracker.transcription.protocol import AudioRef
from tests.fakes import FakeAudioStore, FakeDispatcher
from tests.wav import make_wav

CALL_DATE = date(2026, 10, 21)
UPLOAD_ID = "a" * 32
KEY = f"uploads/{UPLOAD_ID}.wav"
SAMPLE = SampleClip(id="invoice", title="Invoice", duration_ms=41_500, sha256="b" * 64)
NOW = 1_761_000_000.0
TURNS = [Turn(speaker="Ana", text="I will send it."), Turn(speaker="Ben", text="Thanks.")]


class Rig:
    def __init__(self, *, dispatcher: FakeDispatcher | None = None) -> None:
        self.now = NOW
        self.store = MemoryJobStore(clock=lambda: self.now)
        self.audio = FakeAudioStore()
        self.transcriber = FakeTranscriber()
        self.dispatcher = dispatcher if dispatcher is not None else FakeDispatcher()
        self.service = JobService(
            self.store,
            self.audio,
            self.transcriber,
            SampleCatalog([SAMPLE]),
            self.dispatcher,
            clock=lambda: self.now,
        )

    def upload(self, key: str = KEY, *, seconds: float = 2.0, at: int | None = None) -> None:
        self.audio.put(key, make_wav(seconds), uploaded_at_ms=at)


# --- Ids -----------------------------------------------------------------------------------------


def test_the_job_id_depends_on_audio_date_and_names() -> None:
    base = job_id_for("h" * 64, CALL_DATE, ["Ana", "Ben"])
    assert base == job_id_for("h" * 64, CALL_DATE, ["Ana", "Ben"])
    assert len(base) == 64
    assert {
        job_id_for("i" * 64, CALL_DATE, ["Ana", "Ben"]),
        job_id_for("h" * 64, date(2026, 10, 22), ["Ana", "Ben"]),
        job_id_for("h" * 64, CALL_DATE, ["Ben", "Ana"]),
        job_id_for("h" * 64, CALL_DATE, []),
    }.isdisjoint({base})


# --- Uploads -------------------------------------------------------------------------------------


def test_an_upload_starts_transcription() -> None:
    rig = Rig()
    rig.upload(at=int(NOW * 1000) - 4_000)

    job = rig.service.start_upload(UPLOAD_ID, CALL_DATE, ["Ana", "Ben"])

    assert job.status is JobStatus.TRANSCRIBING
    assert job.source is JobSource.UPLOAD
    assert job.audio_key == KEY
    assert job.speaker_names == ["Ana", "Ben"]
    assert job.upload_started_at == int(NOW * 1000) - 4_000
    assert job.created_at == int(NOW * 1000)
    assert job.transcribing_at == int(NOW * 1000)
    assert job.expires_at == int(NOW) + 3600
    assert rig.transcriber.started == [(AudioRef("audio-bucket", KEY), job.id)]
    assert rig.store.get(job.id) == job


def test_a_missing_upload_is_not_found() -> None:
    with pytest.raises(UploadNotFound):
        Rig().service.start_upload(UPLOAD_ID, CALL_DATE, [])


def test_a_clip_that_is_too_long_is_rejected_and_deleted() -> None:
    rig = Rig()
    rig.upload(seconds=60.5)
    with pytest.raises(AudioTooLong):
        rig.service.start_upload(UPLOAD_ID, CALL_DATE, [])
    assert rig.audio.deleted == [KEY]
    assert rig.transcriber.started == []


def test_audio_that_is_not_a_wav_is_rejected_and_deleted() -> None:
    rig = Rig()
    rig.audio.put(KEY, b"not a wav")
    with pytest.raises(AudioInvalid):
        rig.service.start_upload(UPLOAD_ID, CALL_DATE, [])
    assert rig.audio.deleted == [KEY]


def test_the_same_audio_uploaded_again_returns_the_first_job() -> None:
    rig = Rig()
    rig.upload()
    first = rig.service.start_upload(UPLOAD_ID, CALL_DATE, ["Ana", "Ben"])
    second_key = f"uploads/{'c' * 32}.wav"
    rig.upload(second_key)

    again = rig.service.start_upload("c" * 32, CALL_DATE, ["Ana", "Ben"])

    assert again.id == first.id
    assert again.audio_key == KEY
    assert rig.audio.deleted == [second_key]
    assert len(rig.transcriber.started) == 1


def test_a_different_call_date_is_a_different_job() -> None:
    rig = Rig()
    rig.upload()
    a = rig.service.start_upload(UPLOAD_ID, CALL_DATE, [])
    rig.upload(f"uploads/{'c' * 32}.wav")
    b = rig.service.start_upload("c" * 32, date(2026, 10, 22), [])
    assert a.id != b.id
    assert len(rig.transcriber.started) == 2


def test_a_transcription_that_will_not_start_fails_the_job() -> None:
    rig = Rig()
    rig.upload()

    class Broken(FakeTranscriber):
        def start(self, audio: AudioRef, job_id: str) -> None:
            raise RuntimeError("boom")

    service = JobService(
        rig.store, rig.audio, Broken(), SampleCatalog([]), rig.dispatcher, clock=lambda: rig.now
    )

    job = service.start_upload(UPLOAD_ID, CALL_DATE, [])

    assert job.status is JobStatus.FAILED
    assert job.error_code == "transcription_failed"
    assert job.finished_at == int(NOW * 1000)
    assert rig.audio.deleted == [KEY]


# --- Samples -------------------------------------------------------------------------------------


def test_a_sample_skips_the_upload_and_uses_the_catalog_hash() -> None:
    rig = Rig()

    job = rig.service.start_sample("invoice", CALL_DATE, ["Ana", "Ben"])

    assert job.status is JobStatus.TRANSCRIBING
    assert job.source is JobSource.SAMPLE
    assert job.audio_key == "samples/invoice.wav"
    assert job.upload_started_at is None
    assert job.id == job_id_for(SAMPLE.sha256, CALL_DATE, ["Ana", "Ben"])
    assert rig.transcriber.started == [(AudioRef("audio-bucket", "samples/invoice.wav"), job.id)]
    assert rig.audio.deleted == []


def test_an_unknown_sample_is_not_found() -> None:
    with pytest.raises(SampleNotFound):
        Rig().service.start_sample("nope", CALL_DATE, [])


def test_starting_the_same_sample_twice_returns_one_job() -> None:
    rig = Rig()
    first = rig.service.start_sample("invoice", CALL_DATE, [])
    second = rig.service.start_sample("invoice", CALL_DATE, [])
    assert first.id == second.id
    assert len(rig.transcriber.started) == 1


# --- Text ----------------------------------------------------------------------------------------


def test_a_text_job_is_stored_with_its_turns_and_dispatched() -> None:
    rig = Rig()

    job = rig.service.start_text(TURNS, CALL_DATE)

    assert job.status is JobStatus.UPLOADED
    assert job.source is JobSource.TRANSCRIPT
    assert job.audio_key is None
    assert job.turns == TURNS
    assert rig.dispatcher.dispatched == [job.id]
    assert rig.transcriber.started == []


def test_the_same_text_returns_the_first_job_without_dispatching_again() -> None:
    rig = Rig()
    first = rig.service.start_text(TURNS, CALL_DATE)
    second = rig.service.start_text(list(TURNS), CALL_DATE)
    assert second.id == first.id
    assert rig.dispatcher.dispatched == [first.id]


def test_text_and_audio_ids_never_collide() -> None:
    rig = Rig()
    assert rig.service.start_text(TURNS, CALL_DATE).id != job_id_for(SAMPLE.sha256, CALL_DATE, [])


def test_a_dispatch_that_fails_fails_the_job() -> None:
    rig = Rig(dispatcher=FakeDispatcher(error=RuntimeError("down")))

    job = rig.service.start_text(TURNS, CALL_DATE)

    assert job.status is JobStatus.FAILED
    assert job.error_code == "job_start_failed"


def test_text_jobs_need_a_dispatcher() -> None:
    rig = Rig()
    service = JobService(
        rig.store, rig.audio, rig.transcriber, SampleCatalog([]), None, clock=lambda: rig.now
    )
    with pytest.raises(TextJobsUnavailable):
        service.start_text(TURNS, CALL_DATE)


# --- Reading -------------------------------------------------------------------------------------


def test_get_returns_a_job_until_it_expires() -> None:
    rig = Rig()
    job = rig.service.start_sample("invoice", CALL_DATE, [])
    assert rig.service.get(job.id) == job
    rig.now += 3601
    assert rig.service.get(job.id) is None
    assert rig.service.get("0" * 64) is None
